# Kalshi 15m Trading Loop - Gaps, Bugs, and Misalignments

## Executive Summary

This document identifies gaps, bugs, and misalignments discovered during the deep audit of the MERID 5-stage trading loop for BTC/ETH/SOL/XRP/DOGE 15-minute Kalshi contracts.

**Audit Date:** 2025-01-XX  
**Severity Levels:** 
- 🔴 **CRITICAL**: Production-breaking issue, immediate attention required
- 🟠 **HIGH**: Significant issue that could cause data loss or incorrect behavior
- 🟡 **MEDIUM**: Moderate issue that may cause degraded performance or edge case failures
- 🟢 **LOW**: Minor issue or technical debt

---

## CRITICAL Issues (🔴)

### ~~C1: NotImplementedErrors in Execution Path~~ ✅ FALSE POSITIVE

**Location:** `merid/execution/http_base.py`  
**Lines:** 153, 347, 361, 366  
**Severity:** ~~🔴 CRITICAL~~ ✅ FALSE POSITIVE

**Issue:** ~~The HTTP base executor has multiple methods that raise `NotImplementedError`~~

**Resolution:** These are abstract methods marked with `@abstractmethod` in the base class, which is the correct pattern. Subclasses (AlpacaExecutor, KalshiExecutor) must implement these. The `raise NotImplementedError` statements were redundant with the decorator and have been removed for clarity.

**Impact:** ~~If any execution path attempts to use these methods, the application will crash~~ → No impact - these are abstract methods that cannot be instantiated directly.

**Recommendation:** ~~Implement these methods or ensure they are never called in the Kalshi execution path~~ → ✅ Resolved. No action needed.

---

### ~~C2: Live Correlation Bot Crash Fix~~ ✅ RESOLVED

**Location:** `merid/sentiment/live_correlation_bot.py`  
**Lines:** 166-169  
**Severity:** ~~🔴 CRITICAL~~ ✅ RESOLVED

**Issue:** ~~A method intentionally raises `NotImplementedError` to prevent crashes~~

**Resolution:** 
- File marked as `LEGACY / EXPERIMENTAL` with header comment
- `NotImplementedError` replaced with safe stub that returns empty list
- Added `enable_synthetic_markets` flag (defaults to `False`)
- Added warning logs when synthetic markets are attempted
- Bot is not auto-started in production

**Impact:** ~~The sentiment correlation bot cannot function~~ → Bot is explicitly disabled for production to focus on 15m loop.

**Recommendation:** ~~Complete the implementation or document why this functionality is disabled~~ → ✅ Completed. Bot can be re-enabled as separate project after 15m loop is production-ready.

---

## HIGH Issues (🟠)

### ~~H1: Wildcard Imports~~ ✅ FALSE POSITIVE

**Location:** Multiple files  
**Severity:** ~~🟠 HIGH~~ ✅ FALSE POSITIVE

**Issue:** ~~Wildcard imports detected~~

**Resolution:** Grep search found no `from module import *` patterns in the codebase. The dynamic import in `merid/settings.py` (`__import__('time')`) is a legitimate use case for dynamic module loading.

**Impact:** ~~Wildcard imports can cause namespace pollution~~ → No impact - no wildcard imports found.

**Recommendation:** ~~Replace wildcard imports with explicit imports~~ → ✅ Resolved. No action needed.

---

### H2: Empty Exception Handlers (Silent Failures)

**Location:** Multiple files  
**Severity:** ~~🟠 HIGH~~ ✅ PARTIALLY RESOLVED

**Issue:** Multiple `except: pass` patterns found that silently swallow exceptions.

**Resolution:** Fixed 8 critical instances with appropriate logging:
- `top3_edge_allocator.py`: Added warning for invalid env var
- `kalshi_filter_pipeline.py`: Added debug for strike parse failure
- `top3_batch_manager.py`: Added warning for cache shutdown failure
- `kalshi_continuous_trader.py`: Added debug for 6 instances (floor, equity, caps, bankroll, expected move, z-score)
- `ct_profit_taking_integration.py`: Added debug for profit taking signal

**Remaining:** 15+ instances in `kalshi_continuous_trader.py` are fallback logic with comments explaining the fallback behavior. These are lower priority since they have documented fallback paths.

**Impact:** ~~Silent failures can hide bugs~~ → Reduced. Critical paths now log exceptions.

**Recommendation:** ~~Add logging to all exception handlers~~ → ✅ Partially complete. Critical paths have logging. Remaining instances have documented fallback logic.

---

### H3: Threading Lock Usage Without Deadlock Detection

**Location:** Multiple files  
**Severity:** 🟠 HIGH

**Issue:** Multiple threading locks used without deadlock detection or timeout mechanisms:

**Locks found:**
- `merid/whales.py`: `_default_monitor_lock = threading.Lock()`
- `merid/venue_registry.py`: `_registry_lock = threading.Lock()`
- `merid/trading/topn_allocator.py`: `self._lock = threading.RLock()`, `_allocator_lock = threading.Lock()`
- `merid/trading/top3_batch_manager.py`: `_CIRCUIT_BREAKER_LOCK = threading.Lock()`, `self._lock = threading.RLock()`, `_batch_manager_lock = threading.Lock()`
- `merid/trading/kalshi_continuous_trader.py`: `_instance_lock = threading.Lock()`, `_bankroll_config_log_lock = threading.Lock()`, `self._cycle_lock = threading.Lock()`
- `merid/trading/ct_profit_taking_integration.py`: `self._lock = threading.Lock()`
- `merid/trading/ct_execution_adapter.py`: `self._pending_lock = threading.Lock()`

**Impact:** Potential for deadlocks in high-concurrency scenarios. No timeout or deadlock detection means a deadlock could hang the entire process.

**Recommendation:** 
1. Use `threading.Lock` with `acquire(timeout=X)` where possible
2. Add deadlock detection/logging
3. Consider using `asyncio.Lock` for async code paths
4. Implement lock ordering to prevent circular dependencies

**Status:** DEFERRED to future sprint. This is a significant architectural change requiring extensive refactoring. Current locks have been stable in production.

---

## MEDIUM Issues (🟡)

### ~~M1: Abstract Methods Without Implementation~~ ✅ VERIFIED

**Location:** Multiple files  
**Severity:** ~~🟡 MEDIUM~~ ✅ VERIFIED

**Issue:** ~~Abstract methods defined but implementations may be missing~~

**Resolution:** Verified all concrete subclasses implement required abstract methods:
- `OpinionStrategy`: 11 subclasses (HashBiasStrategy, MeanReversionStrategy, etc.) - all implement `estimate()`
- `Forecaster`: 7 subclasses (TimeSeriesForecaster, SentimentForecaster, etc.) - all implement `forecaster_id` and `predict()`
- `DomainAgent`: 4 subclasses (PredictionMarketAgent, CryptoArbAgent, etc.) - all implement `generate_proposals()`
- `UnifiedVenueAdapter`: 1 subclass (KalshiUnifiedAdapter) - implements all 10 abstract methods

**Impact:** ~~If concrete classes don't implement all abstract methods, they cannot be instantiated~~ → No impact. Python's ABC raises TypeError at instantiation if abstract methods are missing. Since these classes are used in production, they must be correctly implemented.

**Recommendation:** ~~Verify all concrete subclasses implement required abstract methods~~ → ✅ Verified. No action needed.

---

### M2: Duplicate Daily Loss Tracking

**Location:** `merid/trading/topn_allocator.py`  
**Lines:** 795, 803  
**Severity:** 🟡 MEDIUM

**Issue:** Comment indicates duplicate daily loss tracking:
```python
# BUG-TNA6: This duplicates daily loss tracking in other systems (fills_ledger, KalshiRiskManager).
```

**Impact:** Multiple systems tracking the same metric can lead to:
- Inconsistent state if one updates but not others
- Performance overhead from redundant calculations
- Confusion about which source is authoritative

**Recommendation:** Consolidate daily loss tracking to a single source of truth. Have other systems read from the authoritative source rather than duplicating logic.

---

### M3: Circuit Breaker Without Metrics

**Location:** `merid/trading/top3_batch_manager.py`  
**Lines:** 94, 150, 156  
**Severity:** 🟡 MEDIUM

**Issue:** Circuit breaker logic exists but may not emit metrics for monitoring:
```python
logger.debug("[TOP3-BATCH] Cache circuit breaker reset after success")
logger.debug("[TOP3-BATCH] Cache circuit open, using in-memory state only")
```

**Impact:** Circuit breaker state changes are logged at DEBUG level, which may not be captured in production monitoring. Operators won't know if the circuit breaker is tripped.

**Recommendation:** 
1. Log circuit breaker state changes at WARNING or ERROR level
2. Emit Prometheus metrics for circuit breaker state
3. Add alerting for circuit breaker trips

---

### M4: Zero/Near-Zero Edge Handling

**Location:** `merid/trading/topn_allocator.py`  
**Lines:** 615, 633  
**Severity:** 🟡 MEDIUM

**Issue:** Special handling for zero/near-zero edges:
```python
# BUG-TNA9: Zero/near-zero edges are handled here by checking edge > min_edge_threshold.
# BUG-TNA9: This ensures zero/near-zero edges are filtered before ranking
```

**Impact:** Zero edges could waste computation cycles or cause unexpected behavior in ranking algorithms.

**Recommendation:** Verify the edge threshold is appropriate for all asset/timeframe combinations. Add unit tests for edge boundary conditions.

---

## LOW Issues (🟢)

### L1: Debug Logging in Production-Critical Paths

**Location:** Multiple files  
**Severity:** 🟢 LOW

**Issue:** Debug logging in critical paths:
- `merid/trading/topn_allocator.py`: Multiple `logger.debug` calls
- `merid/trading/top3_edge_allocator.py`: Multiple `logger.debug` calls
- `merid/trading/top3_batch_manager.py`: Multiple `logger.debug` calls
- `merid/trading/kalshi_continuous_trader.py`: Multiple `logger.debug` calls

**Impact:** Debug logs may not be captured in production, making troubleshooting difficult. Performance impact from excessive logging.

**Recommendation:** 
1. Upgrade critical path logs to INFO level
2. Use structured logging for production
3. Add log sampling for high-frequency events

---

### L2: BUG Comments Without Resolution

**Location:** Multiple files  
**Severity:** 🟢 LOW

**Issue:** Multiple BUG fix comments without follow-up:
- `merid/trading/topn_allocator.py`: BUG-TNA4, BUG-TNA5, BUG-TNA6, BUG-TNA7, BUG-TNA8, BUG-TNA9, BUG-TNA10
- `merid/trading/kalshi_filter_pipeline.py`: BUG-FIX
- `merid/trading/kalshi_continuous_trader.py`: BUG-F2, BUG-SM3

**Impact:** Technical debt accumulation. Unclear if all bugs are truly fixed or if there are known issues.

**Recommendation:** 
1. Create a bug tracking document
2. Resolve or close out old bug comments
3. Add regression tests for each bug fix
4. Consider removing old bug comments after verification

---

### L3: Hard-Coded Security Values

**Location:** `merid/trading/kalshi_continuous_trader.py`  
**Line:** 291  
**Severity:** 🟢 LOW

**Issue:** Security fix hard-coded:
```python
# SECURITY FIX: Hard-coded to 100 (router-only). The direct HTTP bypass
```

**Impact:** While the fix is correct, hard-coding reduces flexibility. If the router needs to be bypassed in emergencies, code changes are required.

**Recommendation:** Make the router percentage configurable via environment variable with a safe default (100). Add runtime validation to ensure the value is >= 100.

---

### L4: Whale Monitor Health Logging

**Location:** `merid/whales.py`  
**Line:** 400  
**Severity:** 🟢 LOW

**Issue:** Health status logged at DEBUG level:
```python
logger.debug(f"WhaleMonitor health: {status}")
```

**Impact:** Whale monitor health may not be visible in production monitoring.

**Recommendation:** Upgrade to INFO level and emit Prometheus metrics for whale monitor health.

---

## Integration Gaps

### G1: Missing Integration Between Components

**Stage 2 → Stage 3 Gap:** Strike Selector to EV Computation
- **Issue:** `KalshiStrikeSelector` validates strikes but may not pass all metadata to `KalshiEdgeMetrics`
- **Impact:** Edge calculations may not have complete strike context
- **Recommendation:** Ensure strike metadata (risk_capped, in_target_band) flows through to edge metrics

**Stage 3 → Stage 4 Gap:** Global Execution Guard to Order Router
- **Issue:** `GlobalExecutionGuard` is a singleton but may not be called by all execution paths
- **Impact:** Some orders may bypass the 2% bankroll cap
- **Recommendation:** Add integration tests to verify all paths call the guard

**Stage 4 → Stage 5 Gap:** Order Router to Fills Ledger
- **Issue:** Order router emits intents but fills ledger may not receive all fills
- **Impact:** P&L tracking may be incomplete
- **Recommendation:** Add reconciliation between intents and fills

---

### G2: Configuration Drift

**Multiple Config Sources:**
- `config/kalshi_distance.yaml` (edge thresholds)
- `config/kalshi_agent_grid.yaml` (agent config)
- `core/settings.py` (risk regime)
- Environment variables (overrides)

**Issue:** Configuration spread across multiple sources can lead to drift and confusion about which source is authoritative.

**Recommendation:** 
1. Document configuration hierarchy clearly
2. Add configuration validation at startup
3. Emit metrics for which config source was used for each value

---

### G3: Sentiment Mode Inconsistency

**Issue:** `SENTIMENT_MODE` can be "gating", "feature_only", or "disabled", but some components may not respect all modes.

**Impact:** Sentiment may block trades when in "feature_only" mode, or may not be used when in "gating" mode.

**Recommendation:** 
1. Add integration tests for each sentiment mode
2. Document which components respect which modes
3. Add runtime validation that sentiment mode is respected

---

## Performance Concerns

### P1: Dual Ingestion Without Deduplication

**Location:** `merid/event_venues/kalshi/fills_ledger.py`

**Issue:** Fills are ingested from both HTTP polling and WebSocket. Deduplication relies on `fill_id` but may not be perfect.

**Impact:** Potential for duplicate fills in the ledger if WS and HTTP paths diverge.

**Recommendation:** 
1. Add stronger deduplication (e.g., hash of fill fields)
2. Add metrics for deduplication rate
3. Add reconciliation job to detect duplicates

---

### P2: Exponential Backoff Without Upper Bound

**Location:** `merid/event_venues/kalshi/market_state.py`  
**Line:** 315

**Issue:** Exponential backoff has a max cap but may still cause long delays:
```python
base_backoff = min(2.0 ** attempt, _CIRCUIT_BREAKER_MAX_BACKOFF_SECONDS)
```

**Impact:** In failure scenarios, recovery may take too long, causing extended downtime.

**Recommendation:** 
1. Add jitter to prevent thundering herd (already implemented)
2. Consider shorter max backoff for high-frequency trading
3. Add manual override for circuit breaker

---

### P3: Market State Store Lock Contention

**Location:** `merid/event_venues/kalshi/market_state.py`

**Issue:** Single lock protects entire state store. High-frequency updates (WS) may cause contention.

**Impact:** Latency in market state updates, especially during high volatility.

**Recommendation:** 
1. Consider per-ticker locks for finer granularity
2. Use lock-free data structures where possible
3. Add metrics for lock contention

---

## Data Flow Issues

### D1: Scope Enforcement Inconsistency

**Location:** Multiple files

**Issue:** Scope enforcement (BTC/ETH/SOL/XRP/DOGE 15m only) is implemented in multiple places:
- `_ALLOWED_SYMBOLS` in ws_bridge.py
- `_ALLOWED_UNDERLYINGS` in market_state.py
- `ALLOWED_ASSETS` in trading_agent.py
- `EXECUTION_TIMEFRAMES` in trading_agent.py

**Impact:** If one enforcement point is missed, non-15m or non-crypto markets could slip through.

**Recommendation:** 
1. Centralize scope enforcement to a single module
2. Have all other components call the centralized function
3. Add integration tests for scope enforcement

---

### D2: Ticker Normalization Inconsistency

**Location:** Multiple files

**Issue:** Ticker normalization is implemented in multiple places:
- `normalize_kalshi_ticker` in settlement_poller.py
- `extract_asset_from_ticker` in trading_agent.py
- `extract_timeframe_from_ticker` in trading_agent.py
- `infer_asset_from_kalshi_market_ticker` in kalshi_crypto_series_meta.py

**Impact:** Inconsistent ticker formats could cause mismatches between components.

**Recommendation:** 
1. Centralize ticker normalization to a single utility module
2. Have all components use the centralized function
3. Add unit tests for all ticker format variations

---

### D3: Spot Price Age Validation Inconsistency

**Location:** Multiple files

**Issue:** Spot price staleness thresholds are defined in multiple places:
- `MAX_PRICE_AGE_SECONDS` in model.py (120s default)
- `max_spot_age_seconds()` function in model.py
- `MERID_PM_MAX_SPOT_AGE_SECONDS` env var

**Impact:** Different components may use different staleness thresholds, leading to inconsistent behavior.

**Recommendation:** 
1. Use a single source of truth for spot staleness
2. Have all components call the centralized function
3. Add metrics for spot price age violations

---

## Security Concerns

### S1: Caller Authorization Whitelist

**Location:** `merid/event_venues/kalshi/order_router.py`

**Issue:** Caller authorization uses a hardcoded whitelist:
```python
_ALLOWED_CALLER_PREFIXES = ("merid.prediction.trading_agent", ...)
```

**Impact:** If new execution paths are added, they must be manually added to the whitelist. Risk of missing a new path.

**Recommendation:** 
1. Make the whitelist configurable via environment variable
2. Add runtime validation that all execution paths are authorized
3. Add alerting for unauthorized execution attempts

---

### S2: Paper Mode Security

**Location:** Multiple files

**Issue:** Paper mode may not be properly isolated from live mode in all components.

**Impact:** Risk of paper trades executing in live mode or vice versa.

**Recommendation:** 
1. Add runtime validation that paper and live modes are properly isolated
2. Add distinct database tables for paper vs live fills
3. Add visual indicators in UI for mode

---

## Testing Gaps

### T1: Missing Integration Tests

**Issue:** While unit tests exist for individual components, end-to-end integration tests may be missing for:
- Full trading loop from market data to execution
- Settlement and P&L calculation
- Circuit breaker behavior
- Failover scenarios

**Recommendation:** 
1. Add end-to-end integration tests for the full loop
2. Add chaos engineering tests for failure scenarios
3. Add performance tests for high-frequency scenarios

---

### T2: Missing Regression Tests

**Issue:** Bug fixes (BUG-TNA*) may not have corresponding regression tests.

**Impact:** Bugs could reappear in future changes.

**Recommendation:** 
1. Add regression tests for each bug fix
2. Link tests to bug tracking system
3. Run regression tests in CI/CD pipeline

---

## Recommendations Summary

### Immediate Actions (This Sprint)

1. **Fix NotImplementedErrors** in execution path (C1, C2)
2. **Replace empty exception handlers** with logging (H2)
3. **Add deadlock detection** to critical locks (H3)
4. **Verify abstract method implementations** (M1)

### Short-Term Actions (Next Sprint)

1. **Consolidate configuration sources** (G2)
2. **Centralize scope enforcement** (D1)
3. **Centralize ticker normalization** (D2)
4. **Add integration tests** (T1)
5. **Add regression tests for bug fixes** (T2)

### Long-Term Actions (This Quarter)

1. **Refactor to per-ticker locks** for market state store (P3)
2. **Implement centralized logging** strategy (L1)
3. **Add comprehensive metrics** for all components
4. **Create bug tracking document** for all BUG comments (L2)
5. **Add chaos engineering** tests (T1)

---

## Conclusion

The MERID 5-stage trading loop is well-architected with clear separation of concerns. However, several issues were identified that could impact production reliability:

- **3 CRITICAL issues** requiring immediate attention
- **3 HIGH issues** that should be addressed soon
- **4 MEDIUM issues** that could cause edge case failures
- **4 LOW issues** representing technical debt

The most concerning issues are:
1. NotImplementedErrors in the execution path (could crash trading)
2. Silent exception handlers (hide bugs)
3. Lack of deadlock detection (could hang the process)

Addressing these issues will significantly improve the reliability and maintainability of the trading system.

---

**End of Gaps, Bugs, and Misalignments Document**
