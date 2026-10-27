# BTC-Anchored Agent Audit Summary (2026-05-15)

## Critical Finding: Duplicate BTC Lane Implementations in Simultaneous Use

### The Problem

The MERID system has **TWO different BTC lane implementations** in use simultaneously:

| Implementation | Used By | Location | Status | Risk |
|----------------|----------|----------|--------|------|
| **Crypto15MLane** | Btc15mAgent | merid/lanes/crypto15m_lane.py | Canonical (PROD_15M_CORE) | Low |
| **BTC15MLane** | Kalshi API, Startup | merid/lanes/btc15m_lane.py | Legacy (ANCIENT_EXPERIMENTAL) | **HIGH** |

### Why This Matters

**Btc15mAgent** (the main trading agent for BTC 15m) uses **Crypto15MLane**:
```python
# Btc15mAgent.configure_dependencies() receives btc_lane parameter
# registry.get_lane("BTC_15M") returns Crypto15MLane instance
btc_lane = registry.get_lane("BTC_15M")
```

**Kalshi API** (lane control operations) uses **BTC15MLane**:
```python
# web/api/kalshi_api.py - Lines 6795, 7280, 7370, 7387, 7406
from merid.lanes.btc15m_lane import _btc15m_lane
from merid.lanes.btc15m_lane import get_btc15m_lane
```

**Startup Agents** (lane orchestrator) uses **BTC15MLane**:
```python
# web/startup_agents.py - Line 173
from merid.lanes.btc15m_lane import get_lane_orchestrator
```

### Risk Assessment

**HIGH RISK** - This inconsistency is a likely source of main loop hangs:

1. **Different Behavior**: The two lane implementations have different logic, different blocking characteristics, and different lifecycle management
2. **State Inconsistency**: If both lanes are running simultaneously, they could have different views of market state, positions, and risk
3. **Blocking Calls**: BTC15MLane (legacy) may have blocking code paths that Crypto15MLane (canonical) doesn't have
4. **Maintenance Burden**: Two implementations to maintain increases bug surface area
5. **Debugging Difficulty**: When a hang occurs, it's unclear which lane is causing it

### Evidence of the Problem

1. **Instrumentation Logs**: The system shows main loop hangs that are hard to diagnose
2. **Missing Method**: Btc15mAgent calls `btc_lane.get_regime_signal()` which doesn't exist on Crypto15MLane (now defensively handled)
3. **Legacy Code**: BTC15MLane has complex sentiment stack, swarm consensus, and risk evaluation that may have blocking calls
4. **API Usage**: Kalshi API actively uses BTC15MLane for lane control operations (start/stop/status)

## Normalization Status

### 15m Asset Agents

| Asset | Agent | Base Class | Dependencies | Normalized |
|-------|-------|------------|--------------|------------|
| **BTC** | Btc15mAgent | Standalone | rti_stream, crypto_rti_monitor, portfolio_risk_agent, kalshi_market_registry, btc_lane, signal_fusion_agent | ⚠️ Partial |
| **ETH** | Eth15mAgent | BaseKalshiAgent | market_registry, crypto_rti_monitor, portfolio_risk_agent | ✅ Yes |
| **SOL** | Sol15mAgent | BaseKalshiAgent | market_registry, crypto_rti_monitor, portfolio_risk_agent | ✅ Yes |
| **XRP** | Xrp15mAgent | BaseKalshiAgent | market_registry, crypto_rti_monitor, portfolio_risk_agent | ✅ Yes |
| **DOGE** | Doge15mAgent | BaseKalshiAgent | market_registry, crypto_rti_monitor, portfolio_risk_agent | ✅ Yes |

**BTC Asymmetry**:
- Uses standalone class instead of BaseKalshiAgent
- Uses sync dependency injection instead of async container.resolve()
- Has unique dependencies: btc_lane, signal_fusion_agent
- Uses custom spec pattern instead of standard Params pattern

**Status**: BTC-only paths are defensively handled, but structural asymmetry remains.

### BTC Anchor Components

| Component | Status | Classification | Notes |
|-----------|--------|----------------|-------|
| **btc_lane (Crypto15MLane)** | ✅ Fixed | KEEP for 15m | Used by Btc15mAgent, defensively handled |
| **signal_fusion_agent** | ✅ Safe | KEEP for 15m | Non-blocking list slice, defensively handled |
| **get_regime_signal()** | ✅ Fixed | KEEP for 15m | Method doesn't exist, now defensively handled with None fallback |
| **BTC15MLane (legacy)** | ⚠️ Active | ANCIENT_EXPERIMENTAL | Used by Kalshi API, HIGH RISK |

## Recommended Actions

### Immediate Actions (P0 - Critical)

1. **Migrate Kalshi API from BTC15MLane to Crypto15MLane**:
   - Update `web/api/kalshi_api.py` to use Crypto15MLane via registry
   - Update `web/startup_agents.py` to use Crypto15MLane via registry
   - Remove direct imports of BTC15MLane
   - Test that lane control operations work with Crypto15MLane

2. **Normalize Btc15mAgent to BaseKalshiAgent pattern**:
   - Make Btc15mAgent extend BaseKalshiAgent
   - Change configure_dependencies() to async with container.resolve()
   - Migrate custom spec pattern to standard Params pattern
   - Keep btc_lane and signal_fusion_agent as optional dependencies

3. **Add defensive tracing to BTC15MLane methods**:
   - Add timing logs to all BTC15MLane methods
   - Add blocking call detection
   - Add exception handling around all external calls

### Medium-Term Actions (P1 - High)

1. **Remove BTC15MLane once migration is complete**:
   - Delete `merid/lanes/btc15m_lane.py`
   - Remove from `merid/lanes/__init__.py`
   - Update all documentation

2. **Remove archived agents**:
   - Delete archived 1h agent files
   - Remove from agent inventory
   - Update tests

3. **Add startup validation**:
   - Check that only Crypto15MLane is used in kalshi_crypto_15m_v2 profile
   - Check that BTC15MLane is not imported in production code
   - Add WARN if legacy lane is detected

## Next Steps

1. **Run system with current instrumentation** to capture logs
2. **Check for [BTC-LANE-MISSING-METHOD] warnings** - should now be logged instead of hanging
3. **Check for [MAIN-LOOP] entering step** logs to see which agent is causing hangs
4. **Migrate Kalshi API to Crypto15MLane** to eliminate the duplicate lane issue
5. **Normalize Btc15mAgent to BaseKalshiAgent pattern** for consistency

## Files Modified

1. `merid/agents/btc_15m_agent.py` - Added defensive exception handling for btc_lane.get_regime_signal()
2. `merid/lanes/btc15m_lane.py` - Added deprecation warning in docstring
3. `docs/audit/KALSHI_15M_AGENT_NORMALIZATION.md` - Detailed lifecycle comparison and BTC-specific dependencies
4. `docs/audit/BTC_LANE_SIGNAL_FUSION_INVESTIGATION.md` - Deep audit of BTC anchor modules and consumers
5. `docs/audit/DUPLICATE_CRYPTO_LANE_GRID_AUDIT.md` - Identified duplicate lane implementations
6. `docs/audit/INSTRUMENTATION_SUMMARY.md` - Complete instrumentation summary

## Conclusion

The main loop hang issue is likely caused by the **duplicate BTC lane implementations**. Btc15mAgent uses Crypto15MLane (canonical) while Kalshi API uses BTC15MLane (legacy). This inconsistency creates state confusion and potential blocking calls in the legacy lane.

**Priority**: Migrate Kalshi API to Crypto15MLane immediately to eliminate this high-risk legacy path.
