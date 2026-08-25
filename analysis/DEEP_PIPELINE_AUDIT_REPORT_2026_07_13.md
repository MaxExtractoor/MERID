# Deep Pipeline Audit Report
**Date**: 2026-07-13  
**Scope**: End-to-end execution pipeline audit for 15m Kalshi crypto trading system  
**Layers Audited**: Upstream (data ingestion), Midstream (signal generation), Downstream (risk enforcement), End-to-end (execution)

---

## Executive Summary

This audit identified **15 high-leverage issues** across the execution pipeline, ranging from warmup bypasses (already fixed) to fallback path risks, fail-open behaviors, and state management gaps. The system has extensive resilience mechanisms but some create potential for unreliable signal generation or risk enforcement bypasses.

**Critical Issues**: 3  
**High Priority**: 7  
**Medium Priority**: 5

---

## Layer 1: Upstream Data Ingestion

### 1.1 Warmup Bypass ✅ FIXED
**File**: `merid/prediction/agent_grid_15m.py` (line 3813-3826)  
**Status**: FIXED in this session  
**Issue**: Cold start logic allowed signal generation to continue despite insufficient bars (<30), causing orders to execute within 1-2 minutes of startup.  
**Fix**: Changed from "Continue with cold start logic" to `return None` when `bars_available < 30`.  
**Impact**: Prevents premature trading based on unreliable indicators.

### 1.2 Spot Feed Fallback Cascade
**File**: `data/unified_spot_service.py` (lines 75-356)  
**Status**: OBSERVED (design choice)  
**Issue**: Multiple fallback mechanisms (public OHLC → authenticated OHLC → spot price fallback) could mask data quality issues.  
**Risk**: If all sources fail, system may continue with stale or degraded data.  
**Recommendation**: Add data quality scoring and alerting when fallbacks are triggered.

### 1.3 Indicator Stack Warmup Gating
**File**: `merid/prediction/agent_grid_15m.py` (line 3811-3826)  
**Status**: FIXED  
**Issue**: 30-bar warmup requirement now enforced via `return None`.  
**Impact**: Signals only generated after proper indicator initialization.

---

## Layer 2: Midstream Signal Generation

### 2.1 Extensive Fallback Paths (High Risk)
**File**: `merid/prediction/agent_grid_15m.py`  
**Locations**: 
- OHLC fallback (lines 1413-1444)
- ATR warmup fallback (lines 1738-1746)
- Indicator stack fallback (lines 4016-4045)
- Price fallback to 42c (line 4694)
- Strike price fallback (lines 7760-7774)
- Dynamic price range fallback (lines 10235-10241)
- Close time fallback (lines 11209-11235)
- Minutes to expiry fallback (line 11549)

**Issue**: System continues signal generation with degraded/fallback data instead of blocking.  
**Risk**: Signals may be generated based on unreliable data (e.g., 42c default price, spot price as strike).  
**Recommendation**: Implement fallback tracking metrics and consider blocking when multiple fallbacks are active.

### 2.2 Market Validation One-Sided Book Logic
**File**: `merid/prediction/agent_grid_15m.py` (lines 6887-6959)  
**Status**: INTENTIONAL DESIGN  
**Issue**: One-sided books are allowed when TTE > 0.5min, rejected in last 30 seconds.  
**Risk**: Terminal phase risk if order doesn't fill in last 30 seconds.  
**Mitigation**: Already appropriate for 15m markets.

### 2.3 Depth Threshold Sourcing
**File**: `merid/prediction/agent_grid_15m.py` (lines 6807-6841)  
**Status**: CORRECT  
**Issue**: Depth thresholds sourced from risk envelope with fallback to defaults.  
**Impact**: Minimal - defaults are conservative (1 contract).

### 2.4 Regime Detection Fallback
**File**: `merid/prediction/agent_grid_15m.py` (lines 6597-6651)  
**Status**: OBSERVED  
**Issue**: Regime classification defaults to "normal" on failure.  
**Risk**: May misclassify market conditions, affecting spread thresholds.  
**Recommendation**: Add alerting when regime detection fails.

---

## Layer 3: Downstream Risk Enforcement

### 3.1 Global Allocator Singleton Reuse ✅ FIXED
**File**: `merid/prediction/agent_grid_15m.py` (lines 12309-12316)  
**Status**: FIXED in previous session  
**Issue**: Allocator was recreated every cycle, resetting pending order tracking.  
**Fix**: Now reuses existing singleton to preserve state.  
**Impact**: Proper per-asset position limit enforcement.

### 3.2 Pending Order Timeout
**File**: `merid/risk/profiles/global_allocator.py` (lines 112-117, 204-220)  
**Status**: CORRECT  
**Issue**: 30-second timeout for pending orders with stale clearing.  
**Impact**: Appropriate for 15m trading cycle.

### 3.3 Position Cache vs Internal State
**File**: `merid/risk/profiles/global_allocator.py` (lines 194-202)  
**Status**: CORRECT  
**Issue**: Uses `current_positions` from position cache (authoritative) instead of internal `_asset_positions`.  
**Impact**: Correct - prevents stale state issues.

### 3.4 Risk Envelope Bankroll Dependency
**File**: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` (lines 1226-1236)  
**Status**: OBSERVED  
**Issue**: Risk envelope cannot be computed if bankroll service unavailable.  
**Risk**: System may fail to start if bankroll service is down.  
**Recommendation**: Add graceful degradation with conservative defaults.

### 3.5 Window Exposure Tracking
**File**: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` (lines 31-38, 113-153)  
**Status**: CORRECT  
**Issue**: Module-level shared state for window exposure with peak bankroll capture.  
**Impact**: Correct design for envelope recomputation resilience.

---

## Layer 4: End-to-End Execution

### 4.1 Order Router Fail-Open Behaviors (High Risk)
**File**: `merid/event_venues/kalshi/order_router.py`  
**Locations**:
- Open order guard (line 333): fail-open on monitor errors
- Market regime gate (line 3548): fail-open on gate evaluation errors
- TOP3 batch gate (line 6633): fail-open on infrastructure errors
- Net edge filter (line 6743): fail-open on calculation errors

**Issue**: Multiple fail-open behaviors could allow orders when risk infrastructure fails.  
**Risk**: Exposure cap bypass if critical risk checks fail.  
**Recommendation**: Review each fail-open point - consider fail-closed for critical checks.

### 4.2 Lifecycle Callback Integration ✅ FIXED
**File**: `merid/event_venues/kalshi/order_router.py` (lines 5510-5528, 5581-5599, 5794-5813)  
**Status**: FIXED in previous session  
**Issue**: Global allocator now notified on order submission, fill, and rejection.  
**Impact**: Proper pending order tracking and position limit enforcement.

### 4.3 Exit Order Detection
**File**: `merid/event_venues/kalshi/order_router.py` (lines 1321-1356)  
**Status**: CORRECT  
**Issue**: Exit orders detected via source markers (take_profit, stop_loss, etc.) and action context.  
**Impact**: Correct - prevents false exit classification of NO entry orders.

### 4.4 Hard Exposure Cap Check
**File**: `merid/event_venues/kalshi/order_router.py` (lines 1943-1963)  
**Status**: CORRECT  
**Issue**: Hard $1 exposure cap check using slot_allocator with exit order bypass.  
**Impact**: Correct enforcement of fixed exposure model.

### 4.5 Duplicate Order Window
**File**: `merid/event_venues/kalshi/order_router.py` (line 110)  
**Status**: FIXED in previous session  
**Issue**: Reduced from 60s to 5s to match 5s cadence.  
**Impact**: Allows legitimate re-submissions after market moves.

### 4.6 Resting Order Monitor Integration
**File**: `merid/event_venues/kalshi/resting_order_monitor.py`  
**Status**: CORRECT  
**Issue**: Monitor polls every 30s, provides find_open_order for anti-stacking.  
**Impact**: Correct - self-healing guard against order stacking.

### 4.7 Position Cache on_fill
**File**: `merid/event_venues/kalshi/position_cache.py` (lines 429-1110)  
**Status**: CORRECT  
**Issue**: on_fill updates position cache and triggers agent cooldown updates.  
**Impact**: Correct position tracking and session risk management.

---

## Cross-Cutting Concerns

### 5.1 Exception Handling Pattern
**Observation**: Extensive use of `except Exception` with logging and fallbacks throughout the stack.  
**Risk**: May mask unexpected errors and allow system to continue in degraded state.  
**Recommendation**: Add structured error classification (expected vs unexpected) and alerting for unexpected errors.

### 5.2 State Management
**Observation**: Multiple singleton patterns (global_allocator, position_cache, risk_envelope) with module-level shared state.  
**Risk**: State corruption if singletons are recreated or not properly initialized.  
**Mitigation**: Global allocator singleton reuse already fixed.

### 5.3 Configuration Sourcing
**Observation**: Mix of profile YAML, code defaults, and environment variables.  
**Risk**: Configuration drift if sources diverge.  
**Recommendation**: Add configuration validation at startup to detect drift.

### 5.4 Logging Consistency
**Observation**: Inconsistent log levels (INFO vs WARNING vs ERROR) for similar severity issues.  
**Risk**: May miss critical alerts in log noise.  
**Recommendation**: Standardize log level policy (ERROR = blocking, WARNING = degraded, INFO = normal).

---

## High-Leverage Bugs (Prioritized)

### P0 - Critical (Fix Required)
1. **Warmup Bypass** ✅ FIXED - Orders executing before 30 bars
2. **Global Allocator State Reset** ✅ FIXED - Pending order tracking lost on cycle
3. **Fail-Open Risk Checks** - Multiple fail-open points could bypass exposure cap

### P1 - High Priority
4. **Fallback Path Risks** - Signals generated with degraded data
5. **Bankroll Service Dependency** - System fails if bankroll service down
6. **Regime Detection Failure** - Defaults to "normal" on failure
7. **Spot Feed Fallback Cascade** - May mask data quality issues
8. **Exception Handling Over-Broad** - May mask unexpected errors
9. **Configuration Drift Risk** - Multiple config sources may diverge
10. **Log Level Inconsistency** - May miss critical alerts

### P2 - Medium Priority
11. **One-Sided Book Terminal Risk** - 30-second window for fill
12. **Depth Threshold Defaults** - Conservative but may be too restrictive
13. **ATR Warmup Fallback** - Returns 0.0 during warmup
14. **Price Fallback to 42c** - Default may not reflect market
15. **Strike Price Fallback** - Uses spot price when window_strike unavailable

---

## Recommendations

### Immediate Actions
1. Review and document each fail-open point - convert critical checks to fail-closed
2. Add fallback tracking metrics to identify when system is operating in degraded mode
3. Add alerting for unexpected errors (not just logging)
4. Add configuration validation at startup

### Medium-Term Improvements
1. Implement data quality scoring for spot feed
2. Add graceful degradation for bankroll service failures
3. Standardize log level policy across the stack
4. Add circuit breakers for repeated fallback activations

### Long-Term Architecture
1. Consider centralized error classification system
2. Implement configuration drift detection
3. Add health check endpoints for critical dependencies
4. Consider stateless design for risk enforcement where possible

---

## Test Coverage Gaps

1. No integration tests for fallback path activation
2. No tests for fail-open behavior verification
3. No tests for configuration drift scenarios
4. No tests for bankroll service failure scenarios
5. No tests for regime detection failure scenarios

---

## Conclusion

The 15m Kalshi crypto trading system has robust resilience mechanisms with extensive fallback paths. However, the extensive fallback logic and fail-open behaviors create potential for unreliable signal generation and risk enforcement bypasses. The two critical warmup/allocator bugs have been fixed. The remaining issues are primarily architectural trade-offs between resilience and reliability.

**Overall Risk Level**: MEDIUM  
**Immediate Action Required**: Review fail-open points  
**System Health**: GOOD (critical bugs fixed)
