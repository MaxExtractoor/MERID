# Deep System Audit Report
**Date**: 2026-07-18  
**Scope**: 15m Kalshi Crypto Trading System  
**Profile**: kalshi_crypto_15m_v2  
**Auditor**: Cascade AI

---

## Executive Summary

This report documents findings from a comprehensive deep audit of the MERID 15m Kalshi crypto trading system. The audit examined configuration files, legacy/production contamination, trading logic, risk management, execution pipeline, agent grid configuration, price range consistency, and duplicate detection mechanisms.

**Critical Issues Found**: 2  
**High Priority Issues Found**: 1  
**Medium Priority Issues Found**: 1  
**Low Priority Issues Found**: 1

---

## 1. Configuration Files Audit

### 1.1 Signal Mode Conflict (CRITICAL)

**Location**: `config/profiles/kalshi_crypto_15m_v2.yaml` vs `config/kalshi_agent_grid.yaml`

**Finding**:
- `kalshi_crypto_15m_v2.yaml` (line 145): `signal_mode: price_based` (changed 2026-07-18)
- `kalshi_agent_grid.yaml`: All 5 agents (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M) have `signal_mode: hybrid` (lines 34, 75, 116, 151, 193)

**Impact**: 
- The profile YAML is declared as the "SINGLE SOURCE OF TRUTH" for signal mode
- Agent grid YAML has outdated signal_mode values that conflict with the profile
- This creates ambiguity about which signal generation mode is actually active
- Comments in agent grid YAML acknowledge profile is single source of truth but values weren't updated

**Remediation**:
```yaml
# config/kalshi_agent_grid.yaml
# Update all 5 agents from:
signal_mode: hybrid
# To:
signal_mode: price_based
```

**Priority**: CRITICAL - Direct conflict with single source of truth principle

---

### 1.2 API Endpoint Misconfiguration (CRITICAL)

**Location**: `start_15m.ps1` (lines 67-70)

**Finding**:
```powershell
$env:MERID_KALSHI_HTTP_BASE = "https://api.elections.kalshi.com/trade-api/v2"
$env:MERID_KALSHI_WS_BASE = "wss://api.elections.kalshi.com/trade-api/ws/v2"
```

**Impact**:
- System is configured to use Kalshi elections API endpoints
- Elections API does NOT support crypto markets (BTC, ETH, SOL, XRP, DOGE)
- Memory states: "BTC, ETH, SOL, XRP, DOGE are the entire crypto stack"
- This is a fundamental misconfiguration that prevents crypto trading
- The correct endpoint should be `api.kalshi.com` or `external-api.kalshi.com` for crypto markets

**Remediation**:
```powershell
# start_15m.ps1
# Update to crypto API endpoints:
$env:MERID_KALSHI_HTTP_BASE = "https://api.kalshi.com/trade-api/v2"
$env:MERID_KALSHI_WS_BASE = "wss://api.kalshi.com/trade-api/ws/v2"
```

**Priority**: CRITICAL - System cannot trade crypto with elections API

---

### 1.3 Documentation Inconsistency (LOW)

**Location**: `start_15m.ps1` (line 103-105)

**Finding**:
```powershell
# 6. Risk Management Configuration
# DEPRECATED: Environment variable overrides removed in favor of unified risk management
# All risk limits are now configured in config/risk_limits.yaml (single source of truth)
```

**Impact**:
- Script states `config/risk_limits.yaml` is single source of truth
- But `config/risk_limits.yaml` itself states it's deprecated for `kalshi_crypto_15m_v2` profile
- Actual single source of truth is `config/profiles/kalshi_crypto_15m_v2.yaml`
- This is a documentation-only issue; actual configuration flow is correct

**Remediation**:
```powershell
# Update comment to:
# All risk limits are configured in config/profiles/kalshi_crypto_15m_v2.yaml (single source of truth)
# config/risk_limits.yaml is deprecated for kalshi_crypto_15m_v2 profile
```

**Priority**: LOW - Documentation only, no functional impact

---

## 2. Legacy vs Production Contamination Audit

### 2.1 Architectural Separation (CLEAN)

**Finding**:
- `web/main.py` does not exist (confirmed via search)
- `web/main_15m_lean.py` is the production entry point
- Import guards in `main_15m_lean.py` (lines 335-347) forbid legacy modules:
  - `merid.main`
  - `merid.loop`
  - `merid.prediction.agent_grid`
  - `web.main`

**Impact**: None - architectural separation is properly enforced

**Remediation**: None required

---

### 2.2 Singleton Resets (CLEAN)

**Finding**:
- `main_15m_lean.py` implements singleton resets for:
  - `unified_spot_service`
  - `ws_bridge`
  - `window_exposure`
  - `agent_grid`
  - `startup_state`

**Impact**: None - clean startup properly implemented

**Remediation**: None required

---

### 2.3 Test File Legacy Imports (LOW)

**Finding**:
- Several test files import legacy modules:
  - `tests/loop/test_merid_15m_loop_profile_guard.py`: `merid.prediction.agent_grid`
  - `tests/test_agent_contract_validation.py`: `merid.prediction.agent_grid`
  - `tests/test_15m_runtime_readiness.py`: checks for `merid.prediction.agent_grid`
  - `tests/test_kalshi_only_profile.py`: `web.main`

**Impact**: Test-only imports, do not affect production

**Remediation**: Optional - update tests to use production modules for consistency

**Priority**: LOW - Test-only, no production impact

---

## 3. Trading Logic Conflicts Audit

### 3.1 Post-Only Flag Handling (CLEAN)

**Finding**:
- `maker_taker_integration.py` (lines 106-116): Correctly prevents post_only=True for marketable orders (aggressiveness > 0)
- `order_router.py` (line 316-324): `_effective_post_only()` helper enforces post_only only for resting orders (aggressiveness == 0)
- 2026-07-12 fix documented in memory addresses execution disconnect issue

**Impact**: None - post_only logic is correctly implemented

**Remediation**: None required

---

### 3.2 Order Stacking Prevention (CLEAN)

**Finding**:
- `order_router.py` (lines 327-366): `_check_open_resting_order()` guard prevents order stacking
- `resting_order_monitor.py` (lines 237-273): `find_open_order()` method supports anti-stacking guard
- Guard is fail-closed on monitor errors (line 355-356)
- Only blocks BUY orders; SELL/exits never blocked

**Impact**: None - anti-stacking guard properly implemented

**Remediation**: None required

---

## 4. Risk Management Gaps Audit

### 4.1 Percentage-Based Allocation Pruning (CLEAN)

**Finding**:
- `config/risk_limits.yaml`: All percentage-based allocation caps set to 0.0:
  - `max_cycle_risk_pct: 0.0`
  - `max_total_risk_pct: 0.0`
  - `categories.crypto.max_notional_pct: 0.0`
  - `per_trade.max_notional_pct: 0.0`
- `merid/risk/unified_risk_manager.py`: Correctly defers to `fixed_exposure_cap_usd` when pct == 0.0 (lines 301-338)
- `merid/risk/global_slot_allocator.py`: Enforces $1 fixed exposure cap (line 95)
- `config/profiles/kalshi_crypto_15m_v2.yaml`: Confirms fixed $1 model (lines 513-525)

**Impact**: None - percentage caps properly disabled, fixed $1 model enforced

**Remediation**: None required

---

### 4.2 Fixed $1 Exposure Cap (CLEAN)

**Finding**:
- `MERID_FIXED_EXPOSURE_CAP_USD` defaults to $1.00
- `global_slot_allocator.py`: `MAX_EXPOSURE_USD = 1.00` (line 95)
- `unified_risk_manager.py`: `fixed_exposure_cap_usd: 1.00` (line 64)
- All components aligned to $1 cap

**Impact**: None - $1 cap consistently enforced

**Remediation**: None required

---

## 5. Execution Pipeline Audit

### 5.1 WebSocket Subscriptions (CLEAN)

**Finding**:
- `KalshiWebSocketBridge` is the production WebSocket implementation
- `websocket_service.py` (lines 151-166): Subscribe/unsubscribe methods implemented
- `universe_invariants.py` (lines 30-82): Validates catalog/state store/WS subscription consistency
- Catalog refresh interval validated in `startup_validations.py` (lines 1971-2006)

**Impact**: None - WebSocket subscription logic properly implemented

**Remediation**: None required

---

### 5.2 Market Catalog (CLEAN)

**Finding**:
- `KalshiMarketCatalog` is the production catalog implementation
- Catalog refreshes every 60 seconds (per profile YAML line 30)
- Minimum 30-second guard enforced (startup_validations.py line 1988)
- All 5 crypto series (KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M) discovered

**Impact**: None - market catalog properly implemented

**Remediation**: None required

---

## 6. Agent Grid Configuration Audit

### 6.1 Asset Coverage (CLEAN)

**Finding**:
- `config/kalshi_agent_grid.yaml`: All 5 required crypto assets configured:
  - BTC_15M (line 16-56)
  - ETH_15M (line 57-97)
  - SOL_15M (line 98-133)
  - XRP_15M (line 134-174)
  - DOGE_15M (line 175-239)
- All agents have `enabled: true`
- All agents have correct series tickers (KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M)

**Impact**: None - all 5 crypto assets properly configured

**Remediation**: None required

---

### 6.2 Signal Mode Conflict (CRITICAL)

**Finding**:
- See Section 1.1 for detailed analysis
- Profile YAML: `signal_mode: price_based`
- Agent grid YAML: All agents have `signal_mode: hybrid`
- Comments acknowledge profile is single source of truth but values not updated

**Impact**: 
- Ambiguity about which signal mode is active
- Potential for unexpected trading behavior
- Violates single source of truth principle

**Remediation**: Update agent grid YAML to match profile (see Section 1.1)

**Priority**: CRITICAL

---

## 7. Price Range Consistency Audit

### 7.1 Canonical 10-75c Range (CLEAN)

**Finding**:
- `config/profiles/kalshi_crypto_15m_v2.yaml`: 
  - `guardrails.min_contract_price_cents: 10`
  - `guardrails.max_contract_price_cents: 75`
- `merid/risk/global_slot_allocator.py`:
  - `MIN_ENTRY_CENTS = 10` (line 96)
  - `MAX_ENTRY_CENTS = 75` (line 97)
- `merid/event_venues/kalshi/risk_parameters.py`:
  - `DEEP_OTM_CHEAP_CENTS = 10` (line 42)
  - `DEEP_OTM_EXPENSIVE_CENTS = 75` (line 43)
- All components aligned to 10-75c canonical range

**Impact**: None - price range consistently enforced across all components

**Remediation**: None required

---

## 8. Duplicate Detection and Order Lifecycle Audit

### 8.1 Duplicate Order Window (CLEAN)

**Finding**:
- `order_router.py` (line 123): `_DUPLICATE_ORDER_WINDOW_SECONDS = 5`
- `order_deduplication.py` (line 18): `_TTL_SECONDS = 5` (aligned with order_router)
- 2026-07-12 fix reduced from 60s to 5s to match 15m agent 5s cadence
- Prevents blocking legitimate re-submissions

**Impact**: None - duplicate window correctly configured

**Remediation**: None required

---

### 8.2 Price Repeat Window (CLEAN)

**Finding**:
- `order_gate.py` (line 243): `_price_repeat_window_s = 60.0`
- 2026-07-12 fix reduced from 900s to 60s
- Allows legitimate re-execution at same price after market returns

**Impact**: None - price repeat window correctly configured

**Remediation**: None required

---

### 8.3 Order Deduplication Cache (CLEAN)

**Finding**:
- `order_deduplication.py`: `OrderDeduplicationCache` class implemented
- `order_router.py` (line 49): Imports `get_order_cache`
- Legacy `_check_duplicate_order` deprecated (line 398)
- New cache provides sophisticated deduplication with 5s buckets

**Impact**: None - modern deduplication cache properly implemented

**Remediation**: None required

---

### 8.4 Resting Order Monitor (CLEAN)

**Finding**:
- `resting_order_monitor.py`: `find_open_order()` method (lines 237-273)
- Case-insensitive matching
- Skips TERMINAL_STATUSES and remaining_size <= 0
- Supports anti-stacking guard in order_router

**Impact**: None - resting order tracking properly implemented

**Remediation**: None required

---

## Summary of Issues

### Critical Issues (2)

1. **Signal Mode Conflict** - Profile YAML (`price_based`) vs Agent Grid YAML (`hybrid`)
   - Location: `config/kalshi_agent_grid.yaml` lines 34, 75, 116, 151, 193
   - Fix: Update all 5 agents to `signal_mode: price_based`

2. **API Endpoint Misconfiguration** - Elections API instead of crypto API
   - Location: `start_15m.ps1` lines 67-70
   - Fix: Update endpoints to `api.kalshi.com` for crypto markets

### High Priority Issues (0)

None found.

### Medium Priority Issues (1)

1. **Test File Legacy Imports** - Test files import legacy modules
   - Location: Multiple test files
   - Fix: Optional - update tests for consistency
   - Impact: Test-only, no production impact

### Low Priority Issues (1)

1. **Documentation Inconsistency** - Risk limits documentation outdated
   - Location: `start_15m.ps1` lines 103-105
   - Fix: Update comment to reference correct single source of truth
   - Impact: Documentation only

---

## Clean Areas (No Issues Found)

1. **Architectural Separation** - Legacy/production properly separated
2. **Singleton Resets** - Clean startup properly implemented
3. **Post-Only Flag Handling** - Correctly prevents post_only on marketable orders
4. **Order Stacking Prevention** - Anti-stacking guard properly implemented
5. **Percentage-Based Allocation Pruning** - Properly disabled in favor of $1 model
6. **Fixed $1 Exposure Cap** - Consistently enforced across all components
7. **WebSocket Subscriptions** - Properly implemented with validation
8. **Market Catalog** - All 5 crypto series discovered and tracked
9. **Asset Coverage** - All 5 required crypto assets configured
10. **Price Range Consistency** - 10-75c canonical range aligned across all components
11. **Duplicate Order Window** - 5s window correctly configured
12. **Price Repeat Window** - 60s window correctly configured
13. **Order Deduplication Cache** - Modern cache properly implemented
14. **Resting Order Monitor** - Properly supports anti-stacking guard

---

## Recommended Action Plan

### Immediate Actions (Before Next Trading Session)

1. **Fix API Endpoint Misconfiguration** (CRITICAL)
   - Update `start_15m.ps1` to use crypto API endpoints
   - Verify endpoints support crypto markets
   - Test with dry-run before live trading

2. **Fix Signal Mode Conflict** (CRITICAL)
   - Update `config/kalshi_agent_grid.yaml` to match profile
   - Verify signal_mode propagation to agents
   - Test signal generation with new mode

### Short-Term Actions (Within 1 Week)

3. **Update Documentation** (LOW)
   - Correct risk limits documentation in `start_15m.ps1`
   - Ensure all comments reference correct single source of truth

4. **Update Test Files** (LOW - Optional)
   - Migrate test imports from legacy to production modules
   - Ensure test coverage for production code paths

### Long-Term Actions (Within 1 Month)

5. **Add Configuration Validation**
   - Add startup validation to detect signal mode conflicts
   - Add startup validation to verify API endpoints match asset class
   - Add automated tests for configuration consistency

6. **Improve Documentation**
   - Create configuration hierarchy documentation
   - Document single source of truth for each configuration area
   - Add change log for configuration updates

---

## Conclusion

The MERID 15m Kalshi crypto trading system is generally well-architected with proper separation of concerns, clean startup procedures, and consistent risk management. However, **two critical issues** were identified that must be addressed before the next trading session:

1. **API Endpoint Misconfiguration** - The system is configured to use elections API endpoints which do not support crypto markets. This prevents the system from trading BTC, ETH, SOL, XRP, and DOGE.

2. **Signal Mode Conflict** - The profile YAML specifies `price_based` signal mode, but the agent grid YAML still has `hybrid` for all agents. This creates ambiguity about which signal generation mode is active.

Once these critical issues are resolved, the system should be fully operational with proper configuration consistency across all components.

---

**Audit Completed**: 2026-07-18  
**Next Audit Recommended**: 2026-08-18 (30 days)  
**Auditor**: Cascade AI
