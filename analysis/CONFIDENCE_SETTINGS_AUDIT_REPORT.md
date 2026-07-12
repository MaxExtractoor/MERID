# Confidence Settings Audit Report
**Date**: 2026-01-18  
**Scope**: Deep audit of confidence settings across MERID 15m Kalshi crypto trading system  
**Assets**: BTC, ETH, SOL, XRP, DOGE

---

## Executive Summary

This audit identified **critical inconsistencies** in confidence threshold usage across the system. The current implementation has **multiple conflicting confidence thresholds** ranging from 0.30 to 0.95, with no single source of truth. While the production profile (`kalshi_crypto_15m_v2.yaml`) uses a 0.65 threshold (aligned with 2026 best practices), legacy code paths and other components use significantly different values, creating potential bugs and inconsistent behavior.

**Key Finding**: The system has **7 different confidence thresholds** across 12+ components, with some legacy paths using 0.50 while production uses 0.65. This creates a high-leverage bug where signals may pass validation in one component but fail in another.

---

## Current Confidence Settings Inventory

### 1. Production Configuration (Single Source of Truth)

**File**: `config/profiles/kalshi_crypto_15m_v2.yaml`

```yaml
confidence:
  min_confidence_threshold: 0.65  # INCREASED from 0.50 to 0.65 (2026-07-03)
  # Rationale: Based on GRDazzle research (0.75 threshold with 83.4% win rate)
  # Industry standard: voltage-kalshi uses 0.55, Predict & Profit uses 0.30
```

**Status**: ✅ **ALIGNED WITH 2026 BEST PRACTICES**  
**Usage**: Primary threshold for 15m crypto trading decisions

---

### 2. Agent Evaluation (Midstream)

**File**: `merid/prediction/quantitative_gates.py`

```python
class GateConfig:
    min_confidence: float = 0.3            # Min confidence to participate
    max_confidence: float = 0.95           # Max confidence (prevents overconfidence)
    confidence_calibration_threshold: float = 0.15  # Max confidence-accuracy gap
```

**Status**: ⚠️ **INCONSISTENT**  
**Issue**: 0.30 min is far below production 0.65, allowing poorly calibrated agents to participate  
**Impact**: Agents with low confidence (0.30-0.65) can pass gates but signals will fail at execution

---

### 3. Signal Validation (Upstream)

**File**: `ai_signals/signal_validation.py`

```python
# Default validation rules
self.default_rules = {
    ValidationRule.CONFIDENCE_THRESHOLD: {
        "min_confidence": 0.6,  # Internal default
        "weight": 0.3
    }
}

# US compliance check
if rule_type == ValidationRule.CONFIDENCE_THRESHOLD:
    # T-038: Raised from 0.5 to 0.65 for trade signals
    if parameters.get("min_confidence", 0) < 0.65:
        return False
```

**Status**: ⚠️ **PARTIALLY ALIGNED**  
**Issue**: Default (0.60) differs from US compliance (0.65) and production (0.65)  
**Impact**: Non-US-compliant paths may use 0.60, creating inconsistency

---

### 4. UI/Display Layer (Downstream)

**File**: `web/read_models/grading.py`

```python
# Filter for display
min_confidence = 0.30
if record.confidence < min_confidence:
    return None

# Executable flag
executable = (
    not record.sim_only and
    record.confidence >= 0.50 and
    record.consensus_confidence >= 0.50
)
```

**Status**: ⚠️ **INCONSISTENT**  
**Issue**: Display threshold (0.30) and executable threshold (0.50) both below production (0.65)  
**Impact**: UI may show signals that would never execute in production, confusing users

---

### 5. Execution Layer (Downstream)

**File**: `merid/event_venues/kalshi/order_router.py`

```python
# Velocity orders
min_confidence_threshold = 0.50  # 50% minimum confidence for velocity orders
if intent.confidence is not None and intent.confidence < min_confidence_threshold:
    return f"confidence_too_low:{intent.confidence}"

# Strategy policy
min_confidence = policy.get("min_confidence", 0.55)  # Default fallback
if intent.confidence is None or intent.confidence < min_confidence:
    return f"missing_or_low_confidence:{intent.confidence}"
```

**Status**: ⚠️ **CRITICAL BUG**  
**Issue**: Velocity orders use 0.50, strategy policy fallback uses 0.55, both below production 0.65  
**Impact**: High-leverage bug - velocity orders may execute with confidence 0.50-0.65 that should be blocked

---

### 6. Legacy Configuration (Non-Production)

**File**: `merid/prediction/trade_hold_config.py`

```python
@dataclass
class StrategyThresholds:
    min_confidence: Decimal = Decimal("0.50")  # LEGACY - NOT USED BY 15m CRYPTO
```

**Status**: ✅ **CORRECTLY LABELED AS LEGACY**  
**Usage**: Only for non-crypto, non-15m agents  
**Impact**: None on 15m crypto stack (intentionally excluded)

---

### 7. Other Components

| Component | Threshold | Status |
|-----------|-----------|--------|
| `crypto_prediction_agent.py` | 0.60 | ⚠️ Below production |
| `arbitrage_agent.py` | 0.85 | ✅ Above production (appropriate for arb) |
| `simulation/mining_engine.py` | 0.70 | ⚠️ Above production (simulation only) |
| `web/api/trading.py` | 0.85 | ✅ Above production (API endpoint) |
| `agents/core/skeptic_agent.py` | 0.80 (veto) | ✅ Appropriate for veto logic |
| `web3/onchain_verifier.py` | 0.80 | ✅ Appropriate for on-chain verification |

---

## 2026 Best Practices Research

### Industry Standards for Prediction Markets

Based on 2026 research from Turbine, AgentBets.ai, and leading prediction market operators:

1. **Minimum Confidence Thresholds**:
   - **GRDazzle**: 0.75 (83.4% win rate reported)
   - **Voltage-Kalshi**: 0.55
   - **Predict & Profit**: 0.30
   - **Industry consensus**: 0.50-0.70 range
   - **Recommended**: 0.65 for balanced signal quality vs. trade volume

2. **Kelly Criterion & Position Sizing**:
   - **Quarter Kelly** (0.25x): Default for most agents
   - **Half Kelly** (0.50x): After 100+ validated bets
   - **Full Kelly**: Never recommended for production
   - **Position caps**: Max 5% per position, 2-3% above $0.70 contract price

3. **Confidence Calibration**:
   - **Calibration threshold**: 0.10-0.15 max error
   - **Brier score**: Key metric for probability accuracy
   - **Reliability plots**: Essential for validation
   - **Wilson lower bound**: Only honest confidence measure for small N

4. **Volatility Regime Awareness**:
   - **High vol regimes**: Reduce confidence thresholds or position size
   - **Regime detection**: Rolling realized-vol z-score
   - **Dynamic adjustment**: Scale down in high vol, don't re-deploy quickly

5. **Fee Considerations**:
   - **Kalshi fees**: 7% × p × (1-p), capped at $0.0175
   - **Breakeven accuracy**: 53% with 50¢ contracts, 55% clears most fee structures
   - **Below 53%**: Fees eat the edge

---

## Gap Analysis

### Critical Issues

#### 1. **Execution Layer Threshold Mismatch (HIGH LEVERAGE BUG)**

**Location**: `merid/event_venues/kalshi/order_router.py`  
**Current**: 0.50 for velocity orders, 0.55 fallback for strategy policy  
**Production Config**: 0.65  
**Gap**: 0.15-0.15 (15-23% below production)  
**Impact**: Signals with confidence 0.50-0.65 may execute when they should be blocked  
**Risk**: HIGH - Direct execution path bypassing production config

**Recommendation**: 
```python
# Fix: Use production config threshold
from config.profiles import get_profile_config
profile = get_profile_config("kalshi_crypto_15m_v2")
min_confidence_threshold = profile.confidence.min_confidence_threshold  # 0.65
```

---

#### 2. **Agent Gate Threshold Too Permissive**

**Location**: `merid/prediction/quantitative_gates.py`  
**Current**: 0.30 min, 0.95 max  
**Production Config**: 0.65 min  
**Gap**: 0.35 (54% below production)  
**Impact**: Poorly calibrated agents (0.30-0.65) can participate but signals fail at execution  
**Risk**: MEDIUM - Wasted computation, confusing agent performance metrics

**Recommendation**:
```python
# Fix: Align with production config
min_confidence: float = 0.65  # Increased from 0.30
max_confidence: float = 0.95  # Keep as-is (prevents overconfidence)
```

---

#### 3. **UI Display/Executable Threshold Mismatch**

**Location**: `web/read_models/grading.py`  
**Current**: 0.30 display, 0.50 executable  
**Production Config**: 0.65  
**Gap**: 0.35-0.15 (54-23% below production)  
**Impact**: UI shows signals that would never execute, confusing users  
**Risk**: LOW - UX issue, no direct execution impact

**Recommendation**:
```python
# Fix: Align display and executable with production
min_confidence = 0.65  # Increased from 0.30
executable = (
    not record.sim_only and
    record.confidence >= 0.65 and  # Increased from 0.50
    record.consensus_confidence >= 0.65  # Increased from 0.50
)
```

---

#### 4. **Signal Validation Default vs US Compliance Mismatch**

**Location**: `ai_signals/signal_validation.py`  
**Current**: 0.60 default, 0.65 US compliance  
**Production Config**: 0.65  
**Gap**: 0.05 (8% below production)  
**Impact**: Non-US paths may use 0.60, creating inconsistency  
**Risk**: MEDIUM - Inconsistent signal quality across compliance modes

**Recommendation**:
```python
# Fix: Unify default with US compliance
self.default_rules = {
    ValidationRule.CONFIDENCE_THRESHOLD: {
        "min_confidence": 0.65,  # Increased from 0.60
        "weight": 0.3
    }
}
```

---

### Medium Priority Issues

#### 5. **Crypto Prediction Agent Threshold**

**Location**: `agents/crypto_prediction_agent.py`  
**Current**: 0.60  
**Production Config**: 0.65  
**Gap**: 0.05 (8% below production)  
**Impact**: Agent may generate signals below production threshold  
**Risk**: MEDIUM - Signal generation below execution threshold

**Recommendation**: Update to 0.65 or make configurable from profile

---

#### 6. **Strategy Policy Fallback in Order Router**

**Location**: `merid/event_venues/kalshi/order_router.py`  
**Current**: 0.55 fallback  
**Production Config**: 0.65  
**Gap**: 0.10 (15% below production)  
**Impact**: If strategy policy missing, uses lower threshold  
**Risk**: MEDIUM - Fallback path may execute low-confidence signals

**Recommendation**: Remove fallback, require explicit policy or use production config

---

### Low Priority / Acceptable Deviations

- **Arbitrage agent (0.85)**: Higher threshold appropriate for arbitrage (different risk profile)
- **Skeptic agent veto (0.80)**: Higher threshold appropriate for veto logic
- **On-chain verifier (0.80)**: Higher threshold appropriate for blockchain verification
- **Simulation mining engine (0.70)**: Simulation-only, not production

---

## Confidence Calibration Analysis

### Current Implementation

**File**: `merid/prediction/quantitative_gates.py`

```python
confidence_calibration_threshold: float = 0.15  # Max confidence-accuracy gap
```

**Assessment**: ✅ **ALIGNED WITH 2026 BEST PRACTICES**  
**Research**: Industry standard is 0.10-0.15  
**Status**: 0.15 is at the upper bound but acceptable

**Recommendation**: Consider tightening to 0.12 for better calibration, but 0.15 is acceptable

---

## Dynamic Confidence Adjustments

### Current Implementation

**File**: `agents/crypto_prediction_agent.py`

```python
# Adaptive threshold adjustment
if accuracy < 0.5:
    self.confidence_threshold = max(0.4, self.confidence_threshold - 0.01)
elif accuracy > 0.7:
    self.confidence_threshold = min(0.8, self.confidence_threshold + 0.01)
```

**Assessment**: ⚠️ **POTENTIALLY DANGEROUS**  
**Issue**: Can lower threshold to 0.40, far below production 0.65  
**Risk**: HIGH - Adaptive logic may bypass production config

**Recommendation**: 
```python
# Fix: Constrain adaptive range to production config
if accuracy < 0.5:
    self.confidence_threshold = max(0.65, self.confidence_threshold - 0.01)  # Floor at 0.65
elif accuracy > 0.7:
    self.confidence_threshold = min(0.80, self.confidence_threshold + 0.01)  # Keep ceiling
```

---

## Volatility Regime Considerations

### Current Implementation

**File**: `config/profiles/kalshi_crypto_15m_v2.yaml`

```yaml
# Per-asset strong thresholds for OBI filter
per_asset_strong_threshold:
  BTC: 0.85
  ETH: 0.85
  SOL: 0.80
  XRP: 0.80
  DOGE: 0.80
```

**Assessment**: ✅ **GOOD PRACTICE**  
**Research**: 2026 best practices recommend regime-aware thresholds  
**Status**: Asset-specific thresholds aligned with volatility profiles

**Recommendation**: Consider adding regime-based confidence scaling (reduce threshold in high vol, increase in low vol)

---

## Recommendations Summary

### Immediate Actions (Critical)

1. **Fix execution layer threshold mismatch** in `order_router.py`:
   - Replace hardcoded 0.50/0.55 with production config 0.65
   - Remove fallback that bypasses production config

2. **Fix agent gate threshold** in `quantitative_gates.py`:
   - Increase min_confidence from 0.30 to 0.65
   - Prevents poorly calibrated agents from participating

3. **Fix adaptive threshold floor** in `crypto_prediction_agent.py`:
   - Constrain adaptive range to not go below 0.65
   - Prevents adaptive logic from bypassing production config

### Short-Term Actions (High Priority)

4. **Unify signal validation thresholds** in `signal_validation.py`:
   - Set default to 0.65 (match US compliance)
   - Eliminate inconsistency between compliance modes

5. **Align UI thresholds** in `grading.py`:
   - Increase display threshold from 0.30 to 0.65
   - Increase executable threshold from 0.50 to 0.65
   - Prevents UI from showing non-executable signals

6. **Update crypto prediction agent**:
   - Increase threshold from 0.60 to 0.65
   - Or make configurable from production profile

### Medium-Term Actions

7. **Implement single source of truth pattern**:
   - Create `confidence_config.py` that reads from production profile
   - All components import from this single source
   - Eliminates hardcoded thresholds across codebase

8. **Add regime-based confidence scaling**:
   - Reduce threshold in high volatility regimes
   - Increase threshold in low volatility regimes
   - Aligns with 2026 best practices

9. **Add confidence telemetry**:
   - Track confidence distribution at each pipeline stage
   - Alert on threshold mismatches
   - Monitor calibration drift

### Long-Term Actions

10. **Implement confidence tier system**:
    - Low (0.65-0.70): Small positions, 1% bankroll
    - Medium (0.70-0.80): Standard positions, 2% bankroll
    - High (0.80-0.95): Large positions, 3-4% bankroll
    - Aligns with IOSG Ventures 2026 research

11. **Add confidence backtesting**:
    - Walk-forward analysis on confidence thresholds
    - Optimize threshold per asset/regime
    - Validate with Wilson lower bound

---

## Testing Recommendations

1. **Unit tests** for threshold consistency:
   - Verify all components use production config threshold
   - Test adaptive logic respects floor/ceiling
   - Validate fallback paths

2. **Integration tests** for end-to-end flow:
   - Signal generation → validation → execution
   - Verify signals below 0.65 never execute
   - Test regime-based adjustments

3. **Backtesting** for threshold optimization:
   - Test 0.60, 0.65, 0.70 thresholds
   - Measure win rate, Sharpe, max drawdown
   - Validate with Wilson lower bound

---

## Conclusion

The current confidence settings have **critical inconsistencies** that create high-leverage bugs. The production configuration (0.65) is well-aligned with 2026 best practices, but multiple code paths use lower thresholds (0.30-0.60), allowing signals to bypass production guardrails.

**Priority**: Fix execution layer and agent gate thresholds immediately to prevent low-confidence signals from executing. Align all components with the production configuration to ensure consistent behavior across the system.

**Risk Assessment**: 
- **Current Risk Level**: HIGH (execution path bypass)
- **After Fixes**: LOW (aligned with 2026 best practices)

**Estimated Effort**: 2-3 days for critical fixes, 1-2 weeks for full alignment
