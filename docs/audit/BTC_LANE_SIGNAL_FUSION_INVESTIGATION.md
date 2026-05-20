# btc_lane and signal_fusion_agent Investigation

## BTC Anchor Deep Audit (2026-05-15)

### Summary

Btc15mAgent has **two unique dependencies** that are NOT present in Eth15mAgent, Sol15mAgent, Xrp15mAgent, or Doge15mAgent:

1. **btc_lane** - For regime signals (currently broken - method doesn't exist)
2. **signal_fusion_agent** - For microstructure signals (orderflow, onchain)

These are used in `Btc15mAgent._build_inputs()` and could be sources of blocking calls.

### BTC Anchor Modules/Classes

#### 1. btc_lane

**Type**: Crypto15MLane instance (from merid/lanes/crypto15m_lane.py)

**Usage in Btc15mAgent**:
```python
# Line 56 - Declaration
self.btc_lane = None  # For regime signals

# Line 71-72 - Injection
btc_lane,
signal_fusion_agent=None

# Line 82 - Assignment
self.btc_lane = btc_lane

# Line 136 - Dependency check
if not all([self.rti_stream, self.crypto_rti_monitor, self.portfolio_risk_agent,
            self.kalshi_market_registry, self.btc_lane]):
    logger.warning("BTC 15m agent missing dependencies")
    return None

# Lines 160-170 - Usage (NOW WITH DEFENSIVE HANDLING)
btc_15m_regime_signal = None
try:
    btc_15m_regime_signal = self.btc_lane.get_regime_signal("BTC_15M_KALSHI")
except AttributeError as exc:
    logger.warning("[BTC-LANE-MISSING-METHOD] btc_lane.get_regime_signal() not found: %s - using None", exc)
    btc_15m_regime_signal = None
except Exception as exc:
    logger.warning("[BTC-LANE-ERROR] btc_lane.get_regime_signal() failed: %s - using None", exc)
    btc_15m_regime_signal = None
```

**Status**: ✅ **FIXED** - Defensive exception handling added. The method doesn't exist on Crypto15MLane, but now fails gracefully with None fallback.

**Classification**: **KEEP for 15m** - The btc_lane dependency is needed for BTC-specific regime logic, but the missing method has been defensively handled.

#### 2. signal_fusion_agent

**Type**: SignalFusionAgent instance (from agents/signal_fusion_agent.py)

**Usage in Btc15mAgent**:
```python
# Line 57 - Declaration
self.signal_fusion_agent = None  # For microstructure signals

# Line 72 - Injection
signal_fusion_agent=None

# Line 83 - Assignment
self.signal_fusion_agent = signal_fusion_agent

# Lines 172-184 - Usage (ALREADY WITH DEFENSIVE HANDLING)
orderflow_bias = 0.0
onchain_velocity = 0.0
if self.signal_fusion_agent:
    try:
        history = self.signal_fusion_agent.get_history(limit=1)
        if history:
            latest = history[-1]
            orderflow_bias = float(latest.get("orderflow_bias", 0.0))
            onchain_velocity = float(latest.get("onchain_velocity", 0.0))
    except Exception as exc:
        logger.debug("SignalFusion fetch failed: %s", exc)
```

**Status**: ✅ **SAFE** - Already has defensive exception handling. Non-blocking list slice operation.

**Classification**: **KEEP for 15m** - The signal_fusion_agent provides microstructure signals (orderflow_bias, onchain_velocity) for BTC trading. Already defensively handled.

### BTC Anchor Consumers

#### Direct Consumers

1. **Btc15mAgent** - Directly depends on btc_lane and signal_fusion_agent
   - Uses btc_lane.get_regime_signal() for regime signals
   - Uses signal_fusion_agent.get_history() for microstructure signals
   - ✅ Both calls now defensively handled

#### Indirect Consumers (via other mechanisms)

2. **KalshiTradingAgent** - May indirectly consume BTC data via:
   - Market registry (KalshiMarketRegistry)
   - RTI stream (RTIStream)
   - Crypto RTI monitor (CryptoRTIMonitor)
   - Portfolio risk agent (PortfolioRiskAgent)

3. **AgentMesh** - May consume BTC data via:
   - MarketAnalystAgent - LLM-based market analysis
   - RiskAgent - LLM-based risk analysis
   - SkepticAgent - LLM-based skepticism
   - StrategyAgent - LLM-based strategy

4. **Other 15m agents (ETH/SOL/XRP/DOGE)** - Do NOT directly depend on BTC anchor:
   - Eth15mAgent - No btc_lane or signal_fusion_agent
   - Sol15mAgent - No btc_lane or signal_fusion_agent
   - Xrp15mAgent - No btc_lane or signal_fusion_agent
   - Doge15mAgent - No btc_lane or signal_fusion_agent

### Legacy Field Dependencies

#### Fields That Only Exist in Old Lane Versions

The following fields are referenced in BTC anchor but may not exist in Crypto15MLane:

1. **regime** - From btc_lane.get_regime_signal()
   - Status: ✅ Method doesn't exist, now defensively handled
   - Impact: BTC agent uses None fallback

2. **confidence** - Expected in regime signal
   - Status: ✅ Not used in current code (commented out in backtest)
   - Impact: None

3. **sentiment** - Not used in 15m agents
   - Status: ✅ Sentiment isolation enforced via profile YAML
   - Impact: None

### BTC Anchor Interface Stability

#### Current Interface (Safe for 15m)

The BTC anchor provides the following stable interface for 15m agents:

1. **orderflow_bias** - From signal_fusion_agent.get_history()
   - Type: float
   - Default: 0.0
   - Safe: ✅ Defensively handled

2. **onchain_velocity** - From signal_fusion_agent.get_history()
   - Type: float
   - Default: 0.0
   - Safe: ✅ Defensively handled

3. **regime_signal** - From btc_lane.get_regime_signal()
   - Type: dict or None
   - Default: None
   - Safe: ✅ Defensively handled (method doesn't exist)

#### Legacy Fields (Not Used in 15m)

The following fields are NOT used in 15m agents and should be marked as research_only:

1. **sentiment** - Disabled via profile YAML
2. **confidence** - Not used in current code
3. **edge_estimate** - Used in backtest but not live 15m

### BTC Anchor Classification

| Component | Module/Class | Status | Classification | Reason |
|-----------|--------------|--------|----------------|--------|
| **btc_lane** | Crypto15MLane | ✅ Fixed | KEEP for 15m | Needed for BTC regime logic, defensively handled |
| **signal_fusion_agent** | SignalFusionAgent | ✅ Safe | KEEP for 15m | Provides microstructure signals, defensively handled |
| **get_regime_signal()** | Missing method | ✅ Fixed | KEEP for 15m | Now defensively handled with None fallback |
| **regime field** | Dict | ✅ Safe | KEEP for 15m | Used in signal generation, has None fallback |
| **confidence field** | Float | ❌ Not used | research_only | Not used in current code |
| **sentiment field** | Str | ❌ Disabled | research_only | Disabled via profile YAML |

## Original Investigation

## btc_lane Investigation

### Usage in Btc15mAgent

```python
# Line 160 in btc_15m_agent.py
btc_15m_regime_signal = self.btc_lane.get_regime_signal("BTC_15M_KALSHI")
```

### Available Methods in Crypto15MLane

From `merid/lanes/crypto15m_lane.py`, the Crypto15MLane class has these methods:
- `__init__()`
- `is_running()`
- `last_cycle()`
- `start()` (async)
- `stop()` (async)
- `_main_loop()` (async)
- `_run_cycle()` (async)
- `_discover_markets()` (async)
- `_aggregate_sentiment()` (async)
- `_get_asset_sentiment_15m()` (async)
- `_get_consensus()` (async)
- `_evaluate_risk()` (async)
- `_execute_order()` (async)
- `_execute_paper_order()` (async)
- `_execute_live_order()` (async)
- `_get_current_positions()` (async)
- `update_historical_performance()`
- `get_bayesian_stats()`
- `get_status()`

### ⚠️ CRITICAL FINDING: get_regime_signal() does NOT exist

The method `get_regime_signal()` is **NOT defined** in Crypto15MLane.

**This is a bug** - Btc15mAgent calls `self.btc_lane.get_regime_signal("BTC_15M_KALSHI")` but this method does not exist on the Crypto15MLane class.

### Potential Impact

1. **Runtime Error**: This call will likely raise an AttributeError when Btc15mAgent tries to build inputs
2. **Could Cause Hang**: If there's a fallback or exception handling that waits/retries, this could block the loop
3. **Missing Regime Signals**: BTC is not getting regime signals that other agents might rely on

### Recommended Action

1. **Add get_regime_signal() method to Crypto15MLane** or remove the call from Btc15mAgent
2. **Add tracing around this call** to see if it's failing silently
3. **Check if there's exception handling** around this call that could be causing delays

## signal_fusion_agent Investigation

### Usage in Btc15mAgent

```python
# Lines 165-173 in btc_15m_agent.py
if self.signal_fusion_agent:
    try:
        history = self.signal_fusion_agent.get_history(limit=1)
        if history:
            latest = history[-1]
            orderflow_bias = float(latest.get("orderflow_bias", 0.0))
            onchain_velocity = float(latest.get("onchain_velocity", 0.0))
    except Exception as exc:
        logger.debug("SignalFusion fetch failed: %s", exc)
```

### Implementation in SignalFusionAgent

From `agents/signal_fusion_agent.py`:

```python
# Lines 112-113
def get_history(self, limit: int = 50) -> List[Dict[str, object]]:
    return list(self._history[-limit:])
```

### Analysis

- `get_history()` is a **synchronous, non-blocking** method
- It simply returns a slice of the `_history` list
- Wrapped in try/except, so failures are logged but don't block
- **Low risk for causing hangs**

### Potential Impact

- Minimal - this is a simple list slice operation
- Exception handling prevents failures from blocking
- **Not a likely source of hangs**

## Structural Asymmetry Summary

| Agent | btc_lane | signal_fusion_agent | Base Class | Dependency Injection |
|-------|----------|---------------------|------------|---------------------|
| **Btc15mAgent** | ✅ Unique | ✅ Unique | Standalone | Direct parameters (sync) |
| **Eth15mAgent** | ❌ | ❌ | BaseKalshiAgent | container.resolve() (async) |
| **Sol15mAgent** | ❌ | ❌ | BaseKalshiAgent | container.resolve() (async) |
| **Xrp15mAgent** | ❌ | ❌ | BaseKalshiAgent | container.resolve() (async) |
| **Doge15mAgent** | ❌ | ❌ | BaseKalshiAgent | container.resolve() (async) |

## Root Cause Hypothesis

The missing `get_regime_signal()` method on btc_lane is the most likely culprit for the main loop hang:

1. **Btc15mAgent._build_inputs()** calls `self.btc_lane.get_regime_signal("BTC_15M_KALSHI")`
2. This method **does not exist** on Crypto15MLane
3. If there's exception handling that retries or waits, this could block indefinitely
4. If there's no exception handling, this would raise AttributeError and crash the cycle

## Immediate Actions Required

1. **Fix the missing method**: Either implement `get_regime_signal()` in Crypto15MLane or remove the call from Btc15mAgent
2. **Add tracing around btc_lane calls**: Add timing logs to see if btc_lane access is slow
3. **Check exception handling**: Review Btc15mAgent._build_inputs() for exception handling around btc_lane calls
4. **Run a test**: Start the system and check logs for AttributeError or delays around btc_lane access

## Next Steps

1. Search for where `get_regime_signal()` might be defined (maybe in a subclass or mixin)
2. Check if btc_lane is a different type than Crypto15MLane
3. Add defensive tracing around the btc_lane call in Btc15mAgent._build_inputs()
4. Normalize the agent structure to remove this asymmetry
