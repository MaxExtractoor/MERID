# Legacy Code & Broken Production Code Audit

**Date**: 2026-05-15  
**Profile**: `kalshi_crypto_15m_v2`  
**Environment**: production (live)

---

## Executive Summary

**Critical Issues**: 2 (blocking production)  
**Legacy Code Still Loaded**: 11 items  
**Production Code Broken**: 7 items  
**Warnings**: 8 items

---

## Critical Issues (Blocking Production)

### 1. UnboundLocalError: 'orchestrator' variable not defined

**Location**: `web/main.py` lines 4035, 4071  
**Error**: `UnboundLocalError: cannot access local variable 'orchestrator' where it is not associated with a value`

**Impact**:
- Agent bridge failed
- Guardrails init failed
- System may not be fully operational

**Logs**:
```
2026-05-15 13:59:54 | WARNING | web.main | Agent bridge failed: cannot access local variable 'orchestrator' where it is not associated with a value
Traceback (most recent call last):
  File "C:\Dev\MERID\web\main.py", line 4035, in _app_lifespan
    registry = get_agent_registry()
    ^^^^^^^^
UnboundLocalError: cannot access local variable 'orchestrator' where it is not associated with a value

2026-05-15 13:59:54 | WARNING | web.main | Guardrails init failed: cannot access local variable 'orchestrator' where it is not associated with a value
Traceback (most recent call last):
  File "C:\Dev\MERID\web\main.py", line 4071, in _app_lifespan
    cap_store = get_capability_store()
    ^^^^^^^^^
UnboundLocalError: cannot access local variable 'orchestrator' where it is not associated with a value
```

**Root Cause**: The `orchestrator` variable is referenced but not initialized in the `_app_lifespan` function when `kalshi_crypto_15m_v2` profile is active.

**Fix Required**: Initialize `orchestrator` variable before use or add conditional logic to handle the case when it's not needed.

---

### 2. RuntimeWarning: Unawaited coroutines in MeridLoop

**Location**: `merid/loop.py` line 1067  
**Error**: `RuntimeWarning: coroutine 'MeridLoop._run_kalshi_agent_cycle' was never awaited`  
**Error**: `RuntimeWarning: coroutine 'CanonicalAgentRegistry.run_all' was never awaited`

**Impact**:
- Agent cycles may not be executing properly
- Potential race conditions or missed opportunities

**Logs**:
```
C:\Dev\MERID\merid\loop.py:1067: RuntimeWarning: coroutine 'MeridLoop._run_kalshi_agent_cycle' was never awaited
  await self._run_agent_cycles(summary)
RuntimeWarning: Enable tracemalloc to get the object allocation traceback

C:\Dev\MERID\merid\loop.py:1067: RuntimeWarning: coroutine 'CanonicalAgentRegistry.run_all' was never awaited
  await self._run_agent_cycles(summary)
RuntimeWarning: Enable tracemalloc to get the object allocation traceback
```

**Root Cause**: Coroutines are created but not awaited in the `_run_agent_cycles` method.

**Fix Required**: Properly await the coroutines or use `asyncio.gather()` for concurrent execution.

---

## Legacy Code Still Loaded

### 1. Crypto Threshold Matrix (Should Not Load)

**Module**: `merid.prediction.crypto_threshold_matrix`  
**Log**: `Loaded crypto threshold matrix from C:\Dev\MERID\config\crypto_threshold_matrix.yaml`

**Issue**: This should NOT be loading for `kalshi_crypto_15m_v2` profile. The profile YAML explicitly sets `use_crypto_threshold_matrix: false`.

**Expected**: Profile guard should prevent this module from loading.

**Fix**: Add profile guard in `merid.prediction.crypto_threshold_matrix` to skip loading when `MERID_PROFILE=kalshi_crypto_15m_v2`.

---

### 2. PM Risk Config Module (Deprecated)

**Module**: `merid.prediction.risk.kalshi_risk_engine`  
**Log**: `PM risk config module merid.prediction.risk.kalshi_risk_engine is loaded. Venue config (merid.event_venues.kalshi.kalshi_risk) is canonical. PM config is deprecated and should not be used in new code.`

**Issue**: Deprecated PM risk config is still being imported/loaded.

**Expected**: Venue config should be the only risk config in use.

**Fix**: Remove imports of this module from production code paths, or add deprecation warning to prevent new usage.

---

### 3. WiredPredictionMarketAgent (Disabled)

**Module**: `merid.agents.wiring`  
**Log**: `PredictionMarketAgentV2 not found in legacy.merid.agents.research - WiredPredictionMarketAgent will use CanonicalAgent as base`  
**Log**: `Skipping PredictionMarketAgent (disabled by feature flag)`

**Issue**: Legacy research agent infrastructure is still present and being checked.

**Expected**: Should be completely removed or disabled for Kalshi-only mode.

**Fix**: This is being skipped correctly, but could be removed entirely for cleaner codebase.

---

### 4. Lane Registry (Empty)

**Module**: `merid.startup_naming_validation`  
**Logs**:
```
WARNING | merid.startup_naming_validation | [NAMING-MISMATCH] Expected lane BTC_15M not found in registry
WARNING | merid.startup_naming_validation | [NAMING-MISMATCH] Expected lane ETH_15M not found in registry
WARNING | merid.startup_naming_validation | [NAMING-MISMATCH] Expected lane SOL_15M not found in registry
WARNING | merid.startup_naming_validation | [NAMING-MISMATCH] Expected lane XRP_15M not found in registry
WARNING | merid.startup_naming_validation | [NAMING-MISMATCH] Expected lane DOGE_15M not found in registry
```

**Issue**: Lane registry is being checked but is empty (0 lanes total). This suggests the lane system is still loaded but not populated.

**Expected**: Either lanes should be populated, or lane registry validation should be skipped for `kalshi_crypto_15m_v2`.

**Fix**: Add profile guard to skip lane registry validation for `kalshi_crypto_15m_v2`, or populate lanes if they're needed.

---

### 5. Regime Agents (Abstract Method Not Implemented)

**Module**: `merid.prediction.agent_grid`  
**Log**: `WARNING | merid.prediction.agent_grid | Regime agents unavailable (kalshi_crypto_15m_v2): Can't instantiate abstract class Btc15mAgent with abstract method get_opinion`

**Issue**: Regime agents are being attempted to instantiate even though they're profile-guarded.

**Expected**: Regime agents should be completely skipped, not attempted.

**Fix**: The profile guard is working (they're skipped), but the error message suggests they're still being checked. Improve the guard logic to prevent instantiation attempts.

---

### 6. Legacy WS Publishers (Skipped - Good)

**Module**: Various legacy WS publisher modules  
**Log**: `Legacy WS publishers SKIPPED (Kalshi-only mode)`

**Status**: ✅ **Correctly skipped** - This is working as intended.

---

### 7. External Sentiment Components (Skipped - Good)

**Modules**: MarketMoodBus, SentimentBus, TwitterStreamHandler, HashtagMonitor, CFGI refresh loop  
**Logs**:
```
INFO | web.main | MarketMoodBus SKIPPED (external sentiment removed from 15m Kalshi production path)
INFO | web.main | SentimentBus SKIPPED (external sentiment removed from 15m Kalshi production path)
INFO | web.main | TwitterStreamHandler SKIPPED (external sentiment removed from 15m Kalshi production path)
INFO | web.main | HashtagMonitor SKIPPED (external sentiment removed from 15m Kalshi production path)
INFO | web.main | CFGI refresh loop SKIPPED (external sentiment removed from 15m Kalshi production path)
```

**Status**: ✅ **Correctly skipped** - This is working as intended.

---

### 8. SpotBasisTracker (Skipped - Intentional)

**Module**: `merid.alignment.spot_basis_tracker`  
**Log**: `[EVENT-LOOP-FIX] SpotBasisTracker skipped (ENABLE_SPOT_BASIS_TRACKER=false - investigating event loop issue)`

**Status**: ✅ **Intentionally skipped** - This is being investigated for event loop issues.

---

### 9. KalshiContinuousTrader (Skipped - Intentional)

**Module**: `merid.trading.kalshi_continuous_trader`  
**Log**: `KalshiContinuousTrader skipped (MERID_ENABLE_KALSHI_CT is false; AgentGrid owns PM execution). Set MERID_ENABLE_KALSHI_CT=true to run CT with the server.`

**Status**: ✅ **Intentionally skipped** - AgentGrid owns PM execution for this profile.

---

### 10. Canonical Agents (Loaded - Expected)

**Modules**: strategy-designer, risk-manager, capital-allocator, anomaly-detector  
**Logs**:
```
INFO | merid.agents.base | Registered canonical agent: strategy-designer (strategy)
INFO | merid.agents.base | Registered canonical agent: risk-manager (risk)
INFO | merid.agents.base | Registered canonical agent: capital-allocator (risk)
INFO | merid.agents.base | Registered canonical agent: anomaly-detector (risk)
```

**Status**: ✅ **Expected** - These are canonical agents that should be loaded.

---

### 11. ReflectionLayer Background Load Failed

**Module**: `agents.reflection`  
**Log**: `WARNING | agents.reflection | ReflectionLayer background load failed: name 'os' is not defined`

**Issue**: Missing import in reflection module.

**Fix**: Add `import os` to the reflection module.

---

## Production Code Broken

### 1. Agent Bridge Failed (Due to orchestrator UnboundLocalError)

**Impact**: Agent registry may not be properly initialized.

**Log**: `WARNING | web.main | Agent bridge failed: cannot access local variable 'orchestrator' where it is not associated with a value`

**Fix**: Fix UnboundLocalError for 'orchestrator' variable (see Critical Issue #1).

---

### 2. Guardrails Init Failed (Due to orchestrator UnboundLocalError)

**Impact**: Capability store may not be properly initialized.

**Log**: `WARNING | web.main | Guardrails init failed: cannot access local variable 'orchestrator' where it is not associated with a value`

**Fix**: Fix UnboundLocalError for 'orchestrator' variable (see Critical Issue #1).

---

### 3. Agent Grid Restrictions Validation Failed

**Module**: `merid.startup_validations`  
**Log**: `WARNING | merid.startup_validations | [PROFILE-RESTRICTION-VALIDATION] Could not validate agent grid restrictions: 'AgentGridConfig' object is not iterable`

**Issue**: Validation logic tries to iterate over `AgentGridConfig` object, which is not iterable.

**Fix**: Fix validation logic to access agent grid config properties correctly.

---

### 4. 15m Series Availability Check Skipped

**Module**: `merid.startup_validations`  
**Log**: `WARNING | merid.startup_validations | [15M-SERIES-VALIDATION] Market catalog module not available - skipping 15m series availability check`

**Issue**: Market catalog module is not available at validation time.

**Fix**: Ensure market catalog is initialized before validation, or defer this check to later.

---

### 5. Lane Registry Naming Mismatches

**Module**: `merid.startup_naming_validation`  
**Logs**:
```
WARNING | merid.startup_naming_validation | [NAMING-WARN] Expected lane BTC_15M for asset BTC not found in registry. Available lanes:
WARNING | merid.startup_naming_validation | [NAMING-WARN] Expected lane ETH_15M for asset ETH not found in registry. Available lanes:
WARNING | merid.startup_naming_validation | [NAMING-WARN] Expected lane SOL_15M for asset SOL not found in registry. Available lanes:
WARNING | merid.startup_naming_validation | [NAMING-WARN] Expected lane XRP_15M for asset XRP not found in registry. Available lanes:
WARNING | merid.startup_naming_validation | [NAMING-WARN] Expected lane DOGE_15M for asset DOGE not found in registry.
```

**Issue**: Lane registry is empty, causing naming validation to fail.

**Fix**: Either populate lanes or skip lane validation for `kalshi_crypto_15m_v2`.

---

### 6. Legacy Lane Usage Check Failed

**Module**: `merid.startup_naming_validation`  
**Log**: `WARNING | merid.startup_naming_validation | Could not check for legacy lane usage: dictionary changed size during iteration`

**Issue**: Dictionary modification during iteration.

**Fix**: Fix iteration logic to use a copy of the dictionary.

---

### 7. ReflectionLayer Background Load Failed

**Module**: `agents.reflection`  
**Log**: `WARNING | agents.reflection | ReflectionLayer background load failed: name 'os' is not defined`

**Issue**: Missing `import os` in reflection module.

**Fix**: Add `import os` to the reflection module.

---

## Warnings (Non-Critical)

### 1. PM Risk Config Deprecated

**Log**: `WARNING | merid.startup_validations | [RISK-CONFIG-VALIDATION] PM risk config module merid.prediction.risk.kalshi_risk_engine is loaded. Venue config (merid.event_venues.kalshi.kalshi_risk) is canonical. PM config is deprecated and should not be used in new code.`

**Status**: ⚠️ **Warning** - Deprecated but not blocking.

---

### 2. Strategy Block Warnings (5 agents)

**Module**: `merid.event_venues.kalshi.grid_validator`  
**Logs**:
```
WARNING | merid.event_venues.kalshi.grid_validator | GRID[BTC/15m] agent=BTC_15M: no explicit strategy: block — using StrategyConfig defaults (7%/6%/5%/4% min_edge tiers). Add a strategy: block to kalshi_agent_grid.yaml for explicit control.
WARNING | merid.event_venues.kalshi.grid_validator | GRID[ETH/15m] agent=ETH_15M: no explicit strategy: block — using StrategyConfig defaults (7%/6%/5%/4% min_edge tiers). Add a strategy: block to kalshi_agent_grid.yaml for explicit control.
WARNING | merid.event_venues.kalshi.grid_validator | GRID[SOL/15m] agent=SOL_15M: no explicit strategy: block — using StrategyConfig defaults (7%/6%/5%/4% min_edge tiers). Add a strategy: block to kalshi_agent_grid.yaml for explicit control.
WARNING | merid.event_venues.kalshi.grid_validator | GRID[XRP/15m] agent=XRP_15M: no explicit strategy: block — using StrategyConfig defaults (7%/6%/5%/4% min_edge tiers). Add a strategy: block to kalshi_agent_grid.yaml for explicit control.
WARNING | merid.event_venues.kalshi.grid_validator | GRID[DOGE/15m] agent=DOGE_15M: no explicit strategy: block — using StrategyConfig defaults (7%/6%/5%/4% min_edge tiers). Add a strategy: block to kalshi_agent_grid.yaml for explicit control.
```

**Status**: ⚠️ **Warning** - Using defaults is acceptable, but explicit strategy blocks would be better.

---

### 3. Coinbase Auth Failed (401)

**Module**: `data.live_price_feed`  
**Log**: `WARNING | data.live_price_feed | [COINBASE-AUTH] Coinbase v3 connection failed with 401 — check that MERID_COINBASE_API_KEY / COINBASE_API_KEY is a valid Advanced Trade API key. Continuing with CCXT fallback.`

**Status**: ⚠️ **Warning** - Falling back to CCXT is acceptable.

---

### 4. Test Fixture Fills Filtered

**Module**: `merid.event_venues.kalshi.fills_ledger`  
**Log**: `WARNING | merid.event_venues.kalshi.fills_ledger | Filtered 5 test-fixture fills from DB (prefixes: fill_integrity_, fill_a_, fill_b_...)`

**Status**: ⚠️ **Warning** - Test data cleanup is expected.

---

### 5. Neo4j Unavailable

**Module**: `db.neo4j`  
**Log**: `WARNING | db.neo4j | Neo4j unavailable — running without graph memory: Couldn't connect to 127.0.0.1:7687 (resolved to ()): Timed out trying to establish connection to ResolvedIPv4Address(('127.0.0.1', 7687))`

**Status**: ⚠️ **Warning** - Graph memory is optional for Kalshi-only mode.

---

### 6. CFB RTI Adapter in Simulation Mode

**Module**: `merid.signals.cfb_rti_adapter`  
**Log**: `WARNING | merid.signals.cfb_rti_adapter | CFB_RTI_ADAPTER_BOOT MERID_CFB_RTI_ADAPTER=simulation implementation=LiveCFBRTIAdapter kalshi_env=live MERID_ALLOW_NULL_CFB=False`

**Status**: ⚠️ **Warning** - Simulation mode for RTI adapter may not be ideal for production.

---

### 7. Promotion Report Fast Mode

**Module**: `merid.promotion_report`  
**Log**: `WARNING | merid.promotion_report | MERID_PROMOTION_REPORT_FAST=true — all promotion rings bypassed; marking all rings passed and clearing blocked-agent list.`

**Status**: ⚠️ **Warning** - Fast mode bypasses promotion checks, which may not be ideal for production.

---

### 8. BTC/ETH Market Enrichment Warning

**Module**: `merid.event_venues.kalshi.market_catalog`  
**Log**: `WARNING | merid.event_venues.kalshi.market_catalog | [CRITICAL-ENRICH] BTC/ETH market found - market_id=KXETH15M-26MAY151400-00 event_ticker= series_ticker=KXETH15M detected_asset=ETH`

**Status**: ⚠️ **Warning** - This appears to be a debug log, not a real issue.

---

## Recommended Action Plan

### Priority 1 (Critical - Fix Immediately)

1. **Fix UnboundLocalError for 'orchestrator'** in `web/main.py` lines 4035, 4071
2. **Fix RuntimeWarning - unawaited coroutines** in `merid/loop.py` line 1067

### Priority 2 (High - Fix Soon)

3. **Add profile guard to crypto_threshold_matrix** to prevent loading for `kalshi_crypto_15m_v2`
4. **Fix agent grid restrictions validation** - fix iteration logic
5. **Fix lane registry** - either populate lanes or skip validation for `kalshi_crypto_15m_v2`
6. **Fix regime agents** - prevent instantiation attempts when profile-guarded
7. **Add missing import** in `agents.reflection` module

### Priority 3 (Medium - Cleanup)

8. **Remove PM risk config imports** from production code paths
9. **Remove WiredPredictionMarketAgent** infrastructure if not needed
10. **Add explicit strategy blocks** to kalshi_agent_grid.yaml for all 5 agents

### Priority 4 (Low - Optional)

11. **Fix 15m series availability check** timing
12. **Fix legacy lane usage check** iteration logic
13. **Review CFB RTI adapter simulation mode** for production
14. **Review promotion report fast mode** for production

---

## Summary

**Total Issues**: 19  
- Critical: 2  
- High: 5  
- Medium: 4  
- Low: 4  
- Warnings: 8

**Status**: System is partially functional but has critical blocking issues that prevent full production readiness.
