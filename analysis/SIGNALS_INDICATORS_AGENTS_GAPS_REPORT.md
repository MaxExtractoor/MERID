# Signals, Indicators, and Agents Gap Analysis Report

**Date**: 2026-07-16  
**Scope**: MERID 15m Kalshi Crypto Trading System  
**Assets**: BTC, ETH, SOL, XRP, DOGE (5 core assets)

---

## Executive Summary

This report documents all gaps and discrepancies identified across the signal generation system, indicator calculations, and agent decision logic within the MERID codebase. The analysis reveals several critical issues including missing implementations, configuration inconsistencies, and potential dead code paths.

---

## 1. Signal Generation System

### 1.1 Components Mapped

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| SignalCalibrator | `merid/prediction/signal_calibrator.py` | ✅ Implemented | Tracks Brier scores for 18 signal names |
| SignalRouter | `merid/event_venues/kalshi/signal_router.py` | ⚠️ Bypassed | NOT used in 15m production stack |
| CryptoSignalsAgent | `merid/agents/crypto_signals_agent.py` | ❌ Stub | `_detect_signals()` returns empty list |
| SignalUniverseService | `merid/event_venues/kalshi/signal_universe_service.py` | ✅ Implemented | Provides filtered market universe |

### 1.2 Critical Gaps

#### GAP 1: CryptoSignalsAgent Stub Implementation
**Location**: `merid/agents/crypto_signals_agent.py:59-60`
```python
async def _detect_signals(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Override point for actual signal detection."""
```
**Issue**: The method is a stub that returns an empty list. The agent is designed to detect spreads, basis, funding, and structural signals across CEXs but does not actually implement this functionality.
**Impact**: No CEX-based signals are being generated for the 15m crypto stack.
**Recommendation**: Implement actual signal detection logic or remove the agent if not needed.

#### GAP 2: SignalRouter Not Used in Production
**Location**: `merid/prediction/kalshi_tools.py:649-650`
```python
# SignalRouter has no subscribers in 15m production stack (no trading_agent)
# Bypassing SignalRouter to ensure global rate limit and cooldown are enforced
```
**Issue**: The SignalRouter pub/sub system is completely bypassed in the 15m production stack. The system was designed to route signals from signal-only agents to trading_agent, but this architecture is not used.
**Impact**: The signal routing infrastructure exists but is dead code in the production path.
**Recommendation**: Either integrate SignalRouter into the production flow or remove it to reduce code complexity.

#### GAP 3: SignalFusion Microstructure Signals Not Implemented
**Location**: `config/kalshi_btc_15m_agent_spec.py:82-89`
```python
# LEAN 15m KALSHI STACK (2026-05-13): SignalFusion microstructure signals
# orderflow_bias > 0 = net aggressive buying / positive imbalance
# orderflow_bias < 0 = net selling / negative imbalance
orderflow_bias: float = 0.0

# onchain_velocity > 0 = above-baseline on-chain activity (z-scored)
# onchain_velocity < 0 = muted activity
onchain_velocity: float = 0.0
```
**Issue**: The agent spec files reference SignalFusion microstructure signals (orderflow_bias, onchain_velocity) but these are not actually generated or consumed in the production code. Grep searches found no implementation of these signals in the prediction module.
**Impact**: The agent specs expect microstructure signals that don't exist in the data flow.
**Recommendation**: Either implement SignalFusion microstructure signal generation or remove these fields from agent specs.

---

## 2. Indicator System

### 2.1 Components Mapped

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Crypto15mIndicatorStack | `merid/signals/crypto_15m_indicators.py` | ✅ Implemented | Core indicator calculation module |
| IndicatorConfig | `merid/signals/crypto_15m_indicators.py` | ✅ Implemented | Asset-specific configurations |
| FVG Detection | `merid/prediction/forecasters/fvg.py` | ✅ Implemented | Fair Value Gap detection |
| OBI Filter | `merid/prediction/order_book_imbalance_filter.py` | ✅ Implemented | Order Book Imbalance filter |

### 2.2 Configuration Inconsistencies

#### INCONSISTENCY 1: Duplicate Agent Spec Files
**Location**: `config/` directory
- **Full spec files**: `kalshi_btc_15m_agent_spec.py`, `kalshi_eth_15m_agent_spec.py`, `kalshi_sol_15m_agent_spec.py`, `kalshi_xrp_15m_agent_spec.py`, `kalshi_doge_15m_agent_spec.py`
- **Simple spec files**: `btc_15m_agent_spec.py`, `eth_15m_agent_spec.py`, `sol_15m_agent_spec.py`, `xrp_15m_agent_spec.py`, `doge_15m_agent_spec.py`

**Issue**: Two sets of agent spec files exist for the same 5 assets. The "kalshi_" prefixed files are more comprehensive (with Kelly sizing, microstructure signals), while the non-prefixed files are simpler (basic regime-based logic).
**Impact**: Unclear which set is the source of truth. Potential for configuration drift.
**Recommendation**: Consolidate to a single source of truth per asset. Remove the unused set.

#### INCONSISTENCY 2: RSI Period Mismatch in Documentation
**Location**: `merid/signals/crypto_15m_indicators.py:91-92`
```python
# CRITICAL FIX: 2026-07-12 - Changed from RSI(8) to RSI(14) for 15-minute markets
# Research shows RSI(14) with 70/30 levels is optimal for 15-minute charts
```
**Issue**: The fix comment indicates RSI was changed from 8 to 14, but need to verify all references are updated.
**Impact**: If any code still references RSI(8), it would be inconsistent with the documented fix.
**Recommendation**: Verify all RSI references use period 14 consistently.

---

## 3. Agent System

### 3.1 Components Mapped

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| LeanAgent15m | `merid/prediction/agent_grid_15m.py` | ✅ Implemented | Core 15m agent class |
| LeanAgentGrid15m | `merid/prediction/agent_grid_15m.py` | ✅ Implemented | Agent grid manager |
| Agent Grid Config | `config/kalshi_agent_grid.yaml` | ✅ Implemented | Agent configuration |
| Profile Config | `config/profiles/kalshi_crypto_15m_v2.yaml` | ✅ Implemented | Single source of truth for risk |

### 3.2 Signal Mode Discrepancies

#### DISCREPANCY 1: Signal Mode Configuration
**Location**: Multiple files
- `config/profiles/kalshi_crypto_15m_v2.yaml:142`: `signal_mode: hybrid`
- `config/kalshi_agent_grid.yaml:31,69,107,139,178`: `signal_mode: momentum_fvg`

**Issue**: The profile YAML sets signal_mode to "hybrid" (combines momentum_fvg with price_based panic fade), but the agent grid YAML sets each agent to "momentum_fvg" only.
**Impact**: The agent grid configuration may override the profile setting, preventing the hybrid strategy from being used.
**Recommendation**: Clarify which configuration takes precedence and ensure consistency.

#### DISCREPANCY 2: Regime Signal References
**Location**: Agent spec files
- `config/kalshi_btc_15m_agent_spec.py:69`: `btc_15m_regime_signal: Dict[str, Any]`
- `config/kalshi_eth_15m_agent_spec.py`: Missing equivalent field
- `config/kalshi_sol_15m_agent_spec.py:55`: `sol_15m_regime_signal: Dict[str, Any]`
- `config/kalshi_xrp_15m_agent_spec.py:55`: `xrp_15m_regime_signal: Dict[str, Any]`
- `config/kalshi_doge_15m_agent_spec.py:55`: `doge_15m_regime_signal: Dict[str, Any]`

**Issue**: The ETH agent spec file does not have the equivalent regime signal field that the other 4 assets have.
**Impact**: Inconsistent input structure across assets.
**Recommendation**: Add `eth_15m_regime_signal` field to ETH agent spec for consistency.

### 3.3 Integration Points

#### INTEGRATION 1: Velocity Threshold Configuration
**Location**: 
- `config/profiles/kalshi_crypto_15m_v2.yaml:1554-1558`: Per-asset velocity thresholds
- `merid/prediction/agent_grid_15m.py:493-513`: Hardcoded velocity thresholds

**Issue**: Velocity thresholds are defined in both the profile YAML and hardcoded in the agent grid. The code has fallback logic to use profile values, but this creates potential for inconsistency.
**Impact**: If profile values are changed, the hardcoded defaults may not align.
**Recommendation**: Ensure profile YAML is the single source of truth and remove hardcoded defaults.

#### INTEGRATION 2: Indicator Stack Initialization
**Location**: `merid/prediction/agent_grid_15m.py:916-966`
**Issue**: Crypto15mIndicatorStack is initialized for all 5 assets, but the initialization is wrapped in a try-except that logs errors and continues without the indicator stack if initialization fails.
**Impact**: If indicator stack initialization fails for any reason, the agent will continue without indicators, potentially leading to poor signal quality.
**Recommendation**: Consider making indicator stack initialization a hard requirement rather than a soft failure.

---

## 4. Data Flow Analysis

### 4.1 Signal-to-Agent Wiring

**Current Flow**:
1. Spot price data → `_update_price_history()` → price history buffer
2. Price history → `Crypto15mIndicatorStack.update()` → indicator snapshot
3. Indicator snapshot + velocity → `_generate_signal()` → trading signal
4. Trading signal → `collect_order_candidate()` → order intent
5. Order intent → order router → execution

**Gaps Identified**:
- **No CEX signal integration**: CryptoSignalsAgent is not wired into the flow
- **No microstructure signal integration**: orderflow_bias and onchain_velocity are not generated
- **SignalRouter bypassed**: The pub/sub signal routing architecture is not used

### 4.2 Configuration Flow

**Current Flow**:
1. `config/profiles/kalshi_crypto_15m_v2.yaml` (single source of truth)
2. Profile adapter → `merid/risk/profiles/crypto_15m_profile.py`
3. Agent grid config → `config/kalshi_agent_grid.yaml`
4. Agent initialization → `LeanAgent15m`

**Inconsistencies**:
- Some parameters are defined in both profile YAML and agent grid YAML
- Agent spec files have their own configurations that may conflict
- Hardcoded defaults in code may override profile settings

---

## 5. Missing Implementations

### 5.1 Stub Implementations

| Component | Location | Current State |
|----------|----------|---------------|
| CryptoSignalsAgent._detect_signals | `merid/agents/crypto_signals_agent.py:59` | Returns empty list |
| Mean reversion signal | `merid/prediction/agent_grid_15m.py:6073` | Implemented but rarely used (requires high confidence) |
| Logit fusion | `merid/prediction/agent_grid_15m.py:6133` | Implemented but mean_reversion_weight=0.3 may be too low |

### 5.2 Dead Code Paths

| Component | Location | Reason |
|----------|----------|--------|
| SignalRouter | `merid/event_venues/kalshi/signal_router.py` | Bypassed in 15m production |
| AgentSignal | `merid/event_venues/kalshi/signal_router.py` | Not used when SignalRouter is bypassed |
| SignalFusion microstructure signals | Referenced in agent specs | Not implemented in production code |
| Legacy agent spec files | `config/btc_15m_agent_spec.py` etc. | Duplicate of kalshi_ prefixed files |

---

## 6. Configuration Inconsistencies Summary

| Parameter | Profile YAML | Agent Grid YAML | Agent Spec | Code Default | Status |
|-----------|--------------|-----------------|------------|-------------|--------|
| signal_mode | hybrid | momentum_fvg | N/A | trend | ⚠️ Inconsistent |
| velocity_threshold_btc | 0.00015 | N/A | N/A | 0.00015 | ✅ Aligned |
| velocity_threshold_eth | 0.00015 | N/A | N/A | 0.00015 | ✅ Aligned |
| velocity_threshold_sol | 0.000225 | N/A | N/A | 0.000225 | ✅ Aligned |
| velocity_threshold_xrp | 0.000225 | N/A | N/A | 0.000225 | ✅ Aligned |
| velocity_threshold_doge | 0.0003 | N/A | N/A | 0.0003 | ✅ Aligned |
| min_edge_threshold | N/A | N/A | 0.012 (BTC) | N/A | ⚠️ Asset-specific |
| max_vol_ratio | N/A | N/A | 2.0 (BTC) | N/A | ⚠️ Asset-specific |

---

## 7. Recommendations

### 7.1 High Priority

1. **Implement or Remove CryptoSignalsAgent**: Either implement actual CEX signal detection or remove the agent to avoid confusion.
2. **Resolve SignalRouter Bypass**: Either integrate SignalRouter into production or remove it as dead code.
3. **Consolidate Agent Spec Files**: Remove duplicate agent spec files and establish a single source of truth per asset.
4. **Implement or Remove SignalFusion References**: Either implement microstructure signal generation or remove references from agent specs.

### 7.2 Medium Priority

5. **Align Signal Mode Configuration**: Ensure signal_mode is consistently defined across profile and agent grid configurations.
6. **Add Missing Regime Signal Field**: Add `eth_15m_regime_signal` to ETH agent spec for consistency.
7. **Verify RSI Period Consistency**: Ensure all RSI references use period 14 consistently.
8. **Make Indicator Stack Initialization Hard Requirement**: Prevent agents from running without indicators.

### 7.3 Low Priority

9. **Remove Hardcoded Defaults**: Ensure profile YAML is the single source of truth for all configurable parameters.
10. **Document Data Flow**: Create comprehensive documentation of the signal-to-agent data flow.

---

## 8. Conclusion

The MERID 15m Kalshi crypto trading system has a well-architected signal, indicator, and agent framework, but several gaps and inconsistencies exist:

- **Critical**: Stub implementations (CryptoSignalsAgent) and bypassed infrastructure (SignalRouter) reduce system effectiveness.
- **Configuration**: Multiple configuration sources create potential for drift and inconsistency.
- **Integration**: Some referenced features (SignalFusion microstructure signals) are not implemented.

Addressing these issues will improve system reliability, maintainability, and performance.

---

**Report Generated**: 2026-07-16  
**Analysis Method**: Static code analysis, grep searches, file reviews  
**Scope**: merid/prediction, merid/agents, merid/signals, config/ directories
