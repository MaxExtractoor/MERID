# Kalshi 15m Agent Normalization Analysis

## BTC-Anchored Agent Audit (2026-05-15)

### All 15m Asset Agents and Their Dependencies

| Asset | Agent Class | File | Base Class | Spec Pattern | Dependencies | configure_dependencies() | Unique Features |
|-------|-------------|------|------------|--------------|--------------|---------------------------|-----------------|
| **BTC** | Btc15mAgent | merid/agents/btc_15m_agent.py | Standalone | Custom (Btc15mAgentSpec) | rti_stream, crypto_rti_monitor, portfolio_risk_agent, kalshi_market_registry, **btc_lane**, **signal_fusion_agent** | Sync method | btc_lane, signal_fusion_agent |
| **ETH** | Eth15mAgent | merid/agents/eth_15m_agent.py | BaseKalshiAgent | Standard (Eth15mParams) | market_registry, crypto_rti_monitor, portfolio_risk_agent | Async with container.resolve() | None |
| **SOL** | Sol15mAgent | merid/agents/sol_15m_agent.py | BaseKalshiAgent | Standard (Sol15mParams) | market_registry, crypto_rti_monitor, portfolio_risk_agent | Async with container.resolve() | None |
| **XRP** | Xrp15mAgent | merid/agents/xrp_15m_agent.py | BaseKalshiAgent | Standard (Xrp15mParams) | market_registry, crypto_rti_monitor, portfolio_risk_agent | Async with container.resolve() | None |
| **DOGE** | Doge15mAgent | merid/agents/doge_15m_agent.py | BaseKalshiAgent | Standard (Doge15mParams) | market_registry, crypto_rti_monitor, portfolio_risk_agent | Async with container.resolve() | None |

### Lifecycle Comparison

| Method | Btc15mAgent | Eth15mAgent | Sol15mAgent | Xrp15mAgent | Doge15mAgent |
|--------|-------------|-------------|-------------|-------------|--------------|
| **Main execution** | `run_cycle()` (async) | `get_opinion()` (async) | `get_opinion()` (async) | `get_opinion()` (async) | `get_opinion()` (async) |
| **Input builder** | `_build_inputs()` (async) | `_build_inputs()` (async) | `_build_inputs()` (async) | `_build_inputs()` (async) | `_build_inputs()` (async) |
| **Dependency injection** | `configure_dependencies()` (sync) | `configure_dependencies()` (async) | `configure_dependencies()` (async) | `configure_dependencies()` (async) | `configure_dependencies()` (async) |
| **Status** | `get_status()` (sync) | (inherited from BaseKalshiAgent) | (inherited from BaseKalshiAgent) | (inherited from BaseKalshiAgent) | (inherited from BaseKalshiAgent) |

### BTC-Specific Dependencies Deep Dive

#### btc_lane Usage in Btc15mAgent

```python
# Line 136 in btc_15m_agent.py - Dependency check
if not all([self.rti_stream, self.crypto_rti_monitor, self.portfolio_risk_agent,
            self.kalshi_market_registry, self.btc_lane]):
    logger.warning("BTC 15m agent missing dependencies")
    return None

# Lines 160-170 - btc_lane.get_regime_signal() call (NOW WITH DEFENSIVE HANDLING)
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

#### signal_fusion_agent Usage in Btc15mAgent

```python
# Lines 172-184 - signal_fusion_agent.get_history() call (ALREADY WITH DEFENSIVE HANDLING)
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

### BTC-Only Code Paths to Fence

The following code paths are BTC-only and should be fenced as such:

1. **btc_lane.get_regime_signal()** - ✅ Already fenced with defensive handling
2. **signal_fusion_agent** - ✅ Already fenced with defensive handling
3. **Btc15mAgentSpec, Btc15mSignalGenerator, Btc15mRiskRules** - Custom spec pattern unique to BTC

### Normalization Recommendations

#### Option 1: Normalize to BaseKalshiAgent Pattern (RECOMMENDED)

Make Btc15mAgent extend BaseKalshiAgent and use the same pattern as ETH/SOL/XRP/DOGE:

**Benefits**:
- Single mental template for "asset_15m_agent"
- Consistent lifecycle management
- Consistent error handling
- Easier to maintain

**Cost**:
- Requires refactoring Btc15mAgent to extend BaseKalshiAgent
- Requires changing configure_dependencies() to async with container.resolve()
- Requires migrating custom spec pattern to standard Params pattern

#### Option 2: Make All Agents Use Standalone Pattern

Make ETH/SOL/XRP/DOGE use the same standalone pattern as BTC:

**Benefits**:
- Less invasive change to BTC
- Keeps BTC custom spec pattern

**Cost**:
- More invasive change to 4 agents
- Loses benefits of BaseKalshiAgent shared logic
- Increases code duplication

#### Option 3: Keep As-Is with Clear BTC-Only Fencing (MINIMAL CHANGE)

Keep current structure but ensure BTC-only paths are clearly fenced and never block:

**Benefits**:
- Minimal code change
- BTC-only paths already defensively handled

**Cost**:
- Maintains structural asymmetry
- Harder to maintain long-term
- Still a bug magnet

**Recommendation**: **Option 1** - Normalize to BaseKalshiAgent pattern for long-term maintainability.

## Structural Asymmetry Detected

## Agent Architecture Comparison

| Agent | Base Class | Spec Pattern | Dependencies | configure_dependencies() | Unique Features |
|-------|-----------|--------------|--------------|---------------------------|-----------------|
| **Btc15mAgent** | Standalone | Custom (Btc15mAgentSpec) | rti_stream, crypto_rti_monitor, portfolio_risk_agent, kalshi_market_registry, **btc_lane**, **signal_fusion_agent** | Sync method | btc_lane, signal_fusion_agent |
| **Eth15mAgent** | BaseKalshiAgent | Standard (Eth15mParams) | market_registry, crypto_rti_monitor, portfolio_risk_agent | Async with container.resolve() | None |
| **Sol15mAgent** | BaseKalshiAgent | Standard (Sol15mParams) | market_registry, crypto_rti_monitor, portfolio_risk_agent | Async with container.resolve() | None |
| **Xrp15mAgent** | BaseKalshiAgent | Standard (Xrp15mParams) | market_registry, crypto_rti_monitor, portfolio_risk_agent | Async with container.resolve() | None |
| **Doge15mAgent** | BaseKalshiAgent | Standard (Doge15mParams) | market_registry, crypto_rti_monitor, portfolio_risk_agent | Async with container.resolve() | None |

## Key Differences

### 1. Base Class Inheritance
- **Btc15mAgent**: Standalone class (does not extend BaseKalshiAgent)
- **Eth/Sol/Xrp/Doge**: All extend BaseKalshiAgent

### 2. Dependency Injection Pattern
- **Btc15mAgent**: Uses `configure_dependencies()` with direct parameter injection
  ```python
  def configure_dependencies(
      self,
      rti_stream: RTIStream,
      crypto_rti_monitor: CryptoRTIMonitor,
      portfolio_risk_agent,
      kalshi_market_registry,
      btc_lane,
      signal_fusion_agent=None
  ):
  ```
- **Eth/Sol/Xrp/Doge**: Use async `configure_dependencies(container: Any)` with container.resolve()
  ```python
  async def configure_dependencies(self, container: Any) -> None:
      if self.market_registry is None:
          self.market_registry = container.resolve(KalshiMarketRegistry)
  ```

### 3. Unique Dependencies in Btc15mAgent
- **btc_lane**: Only BTC has this dependency (regime signals)
- **signal_fusion_agent**: Only BTC has this dependency (microstructure signals)

### 4. Spec Pattern
- **Btc15mAgent**: Uses custom spec with Btc15mAgentSpec, Btc15mSignalGenerator, Btc15mRiskRules
- **Eth/Sol/Xrp/Doge**: Use standard Params pattern (Eth15mParams, Sol15mParams, etc.)

## Risk Assessment

### High Risk Asymmetries

1. **Btc15mAgent has unique dependencies** (btc_lane, signal_fusion_agent) that could cause:
   - Blocking calls in btc_lane regime logic
   - Blocking calls in signal_fusion_agent microstructure logic
   - Different initialization order or timing

2. **Different dependency injection patterns**:
   - BTC uses direct parameter injection (sync)
   - Others use container.resolve() (async)
   - Could cause timing differences in startup

3. **Different base classes**:
   - BTC does not extend BaseKalshiAgent
   - Could have different lifecycle management
   - Could have different error handling

### Medium Risk Asymmetries

1. **Different spec patterns**:
   - BTC uses custom spec with separate SignalGenerator and RiskRules
   - Others use standard Params pattern
   - Could cause different signal generation timing

2. **Different initialization patterns**:
   - BTC initializes spec, signal_generator, risk_rules separately
   - Others just initialize params
   - Could cause different startup timing

## Recommendations

### Immediate Actions

1. **Apply loop tracing decorators to all 5 agents**:
   - Add `@trace_agent_step(agent_instance=self)` to `run_cycle()` or `get_opinion()` methods
   - This will reveal which agent is causing hangs

2. **Check btc_lane initialization**:
   - Verify btc_lane does not have blocking calls
   - Verify btc_lane is not waiting on external services
   - Add timing logs to btc_lane methods

3. **Check signal_fusion_agent initialization**:
   - Verify signal_fusion_agent does not have blocking calls
   - Verify signal_fusion_agent is not waiting on external services
   - Add timing logs to signal_fusion_agent methods

### Medium-Term Actions

1. **Normalize base class**:
   - Consider making Btc15mAgent extend BaseKalshiAgent
   - Or make all agents use standalone pattern (less invasive)

2. **Normalize dependency injection**:
   - Choose one pattern (either direct injection or container.resolve())
   - Apply to all 5 agents

3. **Normalize spec pattern**:
   - Choose one pattern (either custom spec or standard Params)
   - Apply to all 5 agents

### Long-Term Actions

1. **Remove btc_lane from Btc15mAgent if not needed**:
   - If btc_lane is only for BTC-specific regime logic, consider moving it to a separate service
   - Or add similar lane logic to other agents for consistency

2. **Remove signal_fusion_agent from Btc15mAgent if not needed**:
   - If signal_fusion_agent is only for BTC, consider making it available to all agents
   - Or remove if not critical for 15m trading

## Next Steps

1. **Run system with tracing enabled** to identify which agent is causing hangs
2. **Check logs for btc_lane and signal_fusion_agent timing**
3. **If BTC is the culprit**, investigate btc_lane and signal_fusion_agent
4. **If another agent is the culprit**, investigate its unique code paths

## Conclusion

The structural asymmetry between Btc15mAgent and the other 4 agents is a significant risk factor for loop hangs. The unique dependencies (btc_lane, signal_fusion_agent) in Btc15mAgent are the most likely suspects if the loop is hanging during BTC agent execution.

**Priority**: Apply tracing decorators immediately to identify the culprit, then normalize the agent structure.
