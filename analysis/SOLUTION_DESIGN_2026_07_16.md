# Solution Design: MERID 15m Kalshi Crypto Trading System Gaps

**Date**: 2026-07-16  
**Based on**: Web research + codebase analysis  
**Scope**: Address all gaps identified in SIGNALS_INDICATORS_AGENTS_GAPS_REPORT.md

---

## Research Findings Summary

### Signal Routing Architecture
- **Best Practice**: Event-driven pub/sub with subscription routers (symbol → gateway mapping)
- **Low-Latency**: Kernel-bypass networking (DPDK/RDMA) with ring buffers for HFT
- **MERID Context**: SignalRouter exists but is bypassed in 15m production stack
- **Decision**: Remove SignalRouter - it's dead code and the direct signal path is working

### CEX Signal Detection
- **Typical Signals**: Basis (spot-futures spread), funding rates, order flow analysis
- **Use Case**: Arbitrage and market structure analysis across exchanges
- **MERID Context**: CryptoSignalsAgent is a stub for CEX signal detection
- **Decision**: Remove CryptoSignalsAgent - 15m Kalshi is a prediction market system, not CEX arbitrage

### Microstructure Signals
- **OBI (Order Book Imbalance)**: Well-established predictor of short-term price moves (arxiv paper)
- **On-chain Velocity**: Measures transaction activity relative to baseline
- **MERID Context**: Referenced in agent specs but not implemented; OBI is already in momentum_fvg
- **Decision**: Implement SignalFusion microstructure signals - they add value and are referenced

### Configuration Management
- **Best Practice**: Priority order: env vars > YAML > code defaults
- **Pattern**: Singleton configuration loader with schema validation
- **MERID Context**: Profile YAML is source of truth but hardcoded defaults exist
- **Decision**: Remove hardcoded defaults, enforce profile YAML as single source of truth

### RSI Period
- **Research**: RSI(14) is effective for 15-minute charts; some prefer 7-9 for faster signals
- **MERID Context**: Changed from RSI(8) to RSI(14) in 2026-07-12 fix
- **Decision**: Verify RSI(14) is used consistently across all references

---

## Solution Decisions

### HIGH PRIORITY

#### 1. Remove CryptoSignalsAgent (Stub Implementation)
**Rationale**:
- The 15m Kalshi system trades prediction markets, not CEX arbitrage
- CEX signals (basis, funding, spread) are not applicable to Kalshi binary contracts
- The stub returns empty list, providing no value
- Removing it reduces code complexity and confusion

**Implementation**:
- Delete `merid/agents/crypto_signals_agent.py`
- Remove references from `merid/agents/bootstrap.py`
- Update any imports that reference this module
- Add deprecation notice if needed for external consumers

**Impact**: Low - agent is not used in production flow

---

#### 2. Remove SignalRouter (Bypassed Infrastructure)
**Rationale**:
- SignalRouter pub/sub system is completely bypassed in 15m production
- Direct signal generation path is working and simpler
- Event-driven architecture adds complexity without benefit for this use case
- No subscribers exist in production (no trading_agent)

**Implementation**:
- Delete `merid/event_venues/kalshi/signal_router.py`
- Remove bypass comments in `merid/prediction/kalshi_tools.py`
- Clean up any related test files
- Update documentation to reflect direct signal path

**Impact**: Low - infrastructure is not used in production

---

#### 3. Implement SignalFusion Microstructure Signals
**Rationale**:
- Agent specs reference orderflow_bias and onchain_velocity fields
- OBI is already implemented in momentum_fvg strategy
- Research shows microstructure signals are effective for short-horizon returns
- Completes the intended architecture

**Implementation**:
- Create `merid/signals/microstructure_signals.py` module
- Implement orderflow_bias calculation from order book data
- Implement onchain_velocity calculation from transaction data (or proxy from spot velocity)
- Wire these into the agent grid signal generation
- Update agent specs to consume these signals
- Add tests for microstructure signal calculations

**Impact**: Medium - adds new signal sources that may improve edge

---

### MEDIUM PRIORITY

#### 4. Consolidate Duplicate Agent Spec Files
**Rationale**:
- Two sets of agent spec files exist: `kalshi_*_15m_agent_spec.py` and `*_15m_agent_spec.py`
- The kalshi_ prefixed files are more comprehensive (Kelly sizing, microstructure)
- The non-prefixed files are simpler (basic regime-based logic)
- Duplicates create confusion and potential for drift

**Implementation**:
- Keep `kalshi_*_15m_agent_spec.py` files (comprehensive, production-ready)
- Delete `*_15m_agent_spec.py` files (simpler, redundant)
- Verify no code references the deleted files
- Update imports if needed
- Add test to verify only one spec file exists per asset

**Impact**: Low - removes redundancy, clarifies source of truth

---

#### 5. Align signal_mode Configuration
**Rationale**:
- Profile YAML sets `signal_mode: hybrid` (momentum_fvg + price_based panic fade)
- Agent grid YAML sets `signal_mode: momentum_fvg` for each agent
- Inconsistent configuration may prevent hybrid strategy from being used
- Hybrid was added in 2026-07-15 based on Turbine research (+56.6% ROI)

**Implementation**:
- Change agent grid YAML to use `signal_mode: hybrid` for all agents
- Or remove signal_mode from agent grid and let profile override
- Add test to verify signal_mode is consistent across all sources
- Document the priority order: agent grid > profile > code default

**Impact**: Medium - enables hybrid strategy which may improve performance

---

#### 6. Make Indicator Stack Initialization Hard Requirement
**Rationale**:
- Current implementation soft-fails if Crypto15mIndicatorStack init fails
- Agents continue without indicators, potentially leading to poor signals
- Indicators are critical for momentum_fvg strategy (MACD, RSI, OBI)
- Hard requirement prevents silent degradation

**Implementation**:
- Change try-except to raise exception if indicator stack init fails
- Add clear error message indicating which asset failed
- Add startup check to verify all 5 assets have indicator stacks
- Add test to verify hard requirement behavior

**Impact**: Medium - prevents silent failures, ensures signal quality

---

#### 7. Remove Hardcoded Defaults, Use Profile YAML as Single Source of Truth
**Rationale**:
- Velocity thresholds are defined in both profile YAML and hardcoded in agent_grid_15m.py
- Hardcoded defaults may override profile settings
- Best practice is single source of truth with env var override
- Reduces configuration drift

**Implementation**:
- Remove hardcoded velocity thresholds from agent_grid_15m.py
- Ensure profile YAML values are always used
- Add fallback to sensible defaults only if profile is missing
- Add test to verify profile YAML values are used
- Document configuration priority: env vars > profile YAML > code fallback

**Impact**: Medium - improves configuration consistency

---

### LOW PRIORITY

#### 8. Add Missing eth_15m_regime_signal Field
**Rationale**:
- ETH agent spec lacks `eth_15m_regime_signal` field
- Other 4 assets (BTC, SOL, XRP, DOGE) have this field
- Inconsistent input structure across assets
- May cause issues if regime signal is expected

**Implementation**:
- Add `eth_15m_regime_signal: Dict[str, Any]` to Eth15mInputs
- Update should_trade_eth_15m to use regime signal if available
- Add test to verify all 5 assets have regime signal field

**Impact**: Low - consistency improvement, may not be used currently

---

#### 9. Verify and Fix RSI Period Consistency
**Rationale**:
- 2026-07-12 fix changed RSI from 8 to 14 for 15-minute markets
- Need to verify all references use RSI(14) consistently
- Research shows RSI(14) is effective for 15-minute charts

**Implementation**:
- Grep for all RSI period references
- Verify Crypto15mIndicatorStack uses RSI(14)
- Verify momentum_fvg config uses RSI(14)
- Add test to verify RSI period is 14
- Update any remaining RSI(8) references

**Impact**: Low - verification and consistency fix

---

## Implementation Order

### Phase 1: Cleanup (Remove Dead Code)
1. Remove CryptoSignalsAgent
2. Remove SignalRouter
3. Consolidate duplicate agent spec files

### Phase 2: Configuration Fixes
4. Align signal_mode configuration
5. Remove hardcoded defaults
6. Add missing eth_15m_regime_signal field
7. Verify RSI period consistency

### Phase 3: New Features
8. Implement SignalFusion microstructure signals
9. Make indicator stack initialization hard requirement

### Phase 4: Testing
10. Add comprehensive tests for all changes
11. Run all tests and verify they pass

---

## Testing Strategy

### Unit Tests
- Test microstructure signal calculations (orderflow_bias, onchain_velocity)
- Test configuration loading and priority order
- Test agent spec consolidation (verify only one spec per asset)
- Test indicator stack hard requirement (raise on failure)
- Test RSI period consistency

### Integration Tests
- Test signal generation with microstructure signals
- Test hybrid signal mode (momentum_fvg + price_based)
- Test configuration override behavior (env vars > YAML > defaults)
- Test all 5 assets have consistent agent specs

### Regression Tests
- Run existing test suite to ensure no regressions
- Test that production signal generation still works
- Test that velocity thresholds from profile are used
- Test that momentum_fvg strategy still works

---

## Risk Assessment

### High Risk
- **SignalFusion Implementation**: New signal sources may change trading behavior
  - Mitigation: Backtest before production deployment
  - Mitigation: Add feature flag to enable/disable

### Medium Risk
- **Configuration Changes**: signal_mode change to hybrid may increase trade frequency
  - Mitigation: Monitor trade rate in paper trading first
  - Mitigation: Add guardrails for trade frequency

### Low Risk
- **Dead Code Removal**: No impact on production
- **Configuration Consolidation**: Clarifies existing behavior
- **Indicator Stack Hard Requirement**: Prevents silent failures

---

## Rollback Plan

If issues arise after deployment:
1. **SignalFusion**: Add feature flag to disable microstructure signals
2. **signal_mode**: Revert agent grid YAML to momentum_fvg
3. **Indicator Stack**: Revert to soft-fail if init fails
4. **Configuration**: Restore hardcoded defaults as fallback

---

## Success Criteria

- All tests pass (unit, integration, regression)
- No dead code remains
- Configuration is consistent across all sources
- Profile YAML is single source of truth
- Microstructure signals are implemented and tested
- Production signal generation works with new changes
- No increase in error rate or latency

---

**Next Steps**: Begin Phase 1 (Cleanup) by removing dead code
