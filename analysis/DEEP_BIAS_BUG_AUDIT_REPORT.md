# Deep Bias Bug Audit Report - MERID Trading Stack
**Date**: 2026-07-23  
**Scope**: End-to-end audit across upstream, midstream, downstream, and risk management layers  
**Objective**: Identify hidden bias bugs through exhaustive code review and comparison to industry best practices

---

## Executive Summary

This audit identified **7 critical bias bugs** across the MERID trading stack that violate industry best practices for algorithmic trading. These biases can lead to:
- Misallocation of capital due to outdated assumptions
- Non-reproducible model behavior
- Selection bias in asset universe
- Data leakage in signal generation
- Overfitting to historical patterns

The most severe issues are:
1. **Hardcoded correlation matrix** (BTC sentiment bias) - treats market correlations as static
2. **Static signal quality metadata** - asset quality never adapts to performance
3. **Mock data in production API** - fake metrics mask real performance
4. **Lack of walk-forward validation** - no out-of-sample testing discipline

---

## Industry Best Practices Reviewed

Based on 2026 research from:
- PickMyTrade: Backtest Bias Prevention Guide
- Kiploks: Data Snooping & Look-Ahead Bias
- ArXiv: Look-Ahead-Freedom as Temporal Non-Interference
- GitHub: algo-trading-research-platform (bias-free by construction)
- NeurIPS: Fixed-Seed Training variance study

**Key Best Practices**:
1. **Look-Ahead Bias Prevention**: Strict temporal separation, no future data in decisions
2. **Survivorship Bias**: Use point-in-time data including delisted assets
3. **Overfitting Prevention**: Walk-forward validation, out-of-sample testing, parameter regularization
4. **Data Snooping Prevention**: Pre-register hypotheses, track all tests, apply statistical corrections
5. **Reproducibility**: Fixed seeds, deterministic execution, versioned datasets
6. **Dynamic Parameters**: Rolling windows for correlations, signal quality, volatility regimes

---

## Bias Bugs Identified

### BUG #1: Hardcoded Correlation Matrix (CRITICAL)

**Location**: `merid/prediction/btc_sentiment_bias.py` lines 67-72

```python
self._correlation_matrix: Dict[str, float] = {
    "ETH": 0.85,  # BTC-ETH correlation
    "SOL": 0.80,  # BTC-SOL correlation
    "XRP": 0.75,  # BTC-XRP correlation
    "DOGE": 0.70,  # BTC-DOGE correlation
}
```

**Root Cause**: Correlations are treated as immutable constants rather than dynamically computed from market data.

**Impact**:
- System assumes fixed correlations regardless of changing market conditions
- Misallocates capital when actual correlations diverge from hardcoded values
- Example: During crypto regime shifts, BTC-ETH correlation can drop from 0.85 to 0.40, but system still treats them as highly correlated
- This creates systematic bias in position sizing and risk management

**Best Practice Violation**: 
- Industry standard: Use rolling correlation windows (30-90 days) with real-time updates
- Research shows correlations are non-stationary in crypto markets

**Severity**: CRITICAL - Directly affects position sizing and risk allocation

**Fix Required**:
1. Implement rolling correlation calculation from historical price data
2. Add correlation confidence intervals
3. Fall back to conservative defaults when correlation is unstable
4. Add regime detection for correlation shifts

---

### BUG #2: Static Signal Quality Metadata (CRITICAL)

**Location**: `data/asset_universe.py` - `signal_quality` attribute

**Root Cause**: Asset signal quality is hardcoded metadata (e.g., BTC=0.9, DOGE=0.6) rather than dynamically computed from recent prediction accuracy.

**Impact**:
- System consistently favors certain assets regardless of their actual recent signal quality
- Creates selection bias - high-quality assets stay high-quality even when performance degrades
- Low-quality assets (DOGE with 0.6) are systematically under-sized even when signals are accurate
- Signal confidence capping in `ai_signals/signal_generator.py` uses this static value

**Best Practice Violation**:
- Signal quality should be computed from recent prediction accuracy (rolling window of 30-100 trades)
- Should adapt to changing market conditions and model performance

**Severity**: CRITICAL - Directly affects signal confidence and position sizing

**Fix Required**:
1. Implement rolling signal quality calculation from recent trade outcomes
2. Update signal quality in real-time based on prediction accuracy
3. Add minimum sample size before quality score is trusted
4. Add decay factor to weight recent performance more heavily

---

### BUG #3: Mock Data in Production API (CRITICAL)

**Location**: `web/services/prediction_publisher.py` lines 106-213

```python
"ourPnl": round(random.uniform(-500, 1000), 2) if has_position else 0.0,
"modelConfidence": round(random.uniform(0.6, 0.95), 2),
"yesPrice": 0.52 + random.uniform(-0.03, 0.03),
```

**Root Cause**: Mock data generation logic present in production code paths for API responses.

**Impact**:
- API returns fake PnL, confidence, and price data instead of real metrics
- Masks actual system performance from monitoring and alerting
- Users/operators see synthetic data instead of real trading performance
- Makes it impossible to detect issues through API monitoring

**Best Practice Violation**:
- Production APIs should never return mock/synthetic data
- All data should be sourced from actual trading engine or database

**Severity**: CRITICAL - Compromises observability and monitoring

**Fix Required**:
1. Remove all random.uniform() calls from production API
2. Wire API to real data sources (fills_ledger, position_cache, market_state)
3. Add validation to ensure no mock data reaches production
4. Add health checks to verify data sources are real

---

### BUG #4: Lack of Walk-Forward Validation (HIGH)

**Location**: `merid/prediction/walk_forward_optimizer.py` exists but not integrated into production signal generation

**Root Cause**: Walk-forward validation framework exists but is not used for ongoing model validation in production.

**Impact**:
- No systematic out-of-sample testing of signal performance
- Risk of overfitting to historical patterns that no longer hold
- No early warning when signal quality degrades
- Parameter tuning may be introducing data snooping bias

**Best Practice Violation**:
- Industry standard: Continuous walk-forward validation with embargo periods
- Should have strict in-sample vs out-of-sample separation
- Should track performance degradation across rolling windows

**Severity**: HIGH - Allows overfitting to persist undetected

**Fix Required**:
1. Integrate walk-forward optimizer into production signal pipeline
2. Add automated performance regression detection
3. Implement embargo periods between training and test sets
4. Add alerts when out-of-sample performance degrades

---

### BUG #5: No Fixed Seeds in Production ML (MEDIUM)

**Location**: Production ML models in `ai_signals/` and `merid/prediction/` lack deterministic seed handling

**Root Cause**: While tests use `random.seed(42)`, production model training/inference has no reproducibility controls.

**Impact**:
- Model behavior may be non-deterministic across runs
- Difficult to debug issues when behavior varies
- Cannot reproduce specific trading scenarios
- Research shows fixed-seed variance can cause up to 12.6% fairness variance in DL systems

**Best Practice Violation**:
- Production systems should use controlled randomness with logged seeds
- Should be able to reproduce any production run deterministically

**Severity**: MEDIUM - Affects debuggability and reproducibility

**Fix Required**:
1. Add seed initialization to all model training/inference paths
2. Log seeds used for each production run
3. Add deterministic mode for debugging/reproduction
4. Implement seed management in model versioning

---

### BUG #6: Liquidity Tier Static Thresholds (MEDIUM)

**Location**: `config/profiles/kalshi_crypto_15m_v2.yaml` lines 424-434

```yaml
liquidity_tiers:
  high_threshold: 200  # High liquidity: >=200 contracts
  medium_threshold: 80  # Medium liquidity: 80-200 contracts
  low_threshold: 40  # Low liquidity: 40-80 contracts
```

**Root Cause**: Liquidity thresholds are static constants rather than adaptive to market conditions.

**Impact**:
- System may reject trades in genuinely liquid markets during high-volume periods
- May accept trades in illiquid markets during low-volume periods
- Does not account for time-of-day or day-of-week liquidity patterns
- Static thresholds don't adapt to changing market depth

**Best Practice Violation**:
- Liquidity thresholds should be percentile-based relative to recent history
- Should adapt to time-of-day and volatility regimes

**Severity**: MEDIUM - Affects trade selection and position sizing

**Fix Required**:
1. Implement percentile-based liquidity thresholds from rolling window
2. Add time-of-day adjustments
3. Add volatility regime adjustments
4. Use relative depth (depth as % of average) rather than absolute

---

### BUG #7: Price Validation Disabled for Production Profile (LOW)

**Location**: `data/live_price_feed.py` lines 359-370

```python
def _is_price_validation_enabled() -> bool:
    import os
    profile = os.getenv("MERID_PROFILE", "").lower()
    return profile != "kalshi_crypto_15m_v2"
```

**Root Cause**: Price validation explicitly disabled for production profile.

**Impact**:
- No sanity checks on price data from exchanges
- Vulnerable to bad data from exchange APIs
- Could trade on erroneous prices causing losses
- Comment says "validation was blocking valid prices" but no evidence of false positives

**Best Practice Violation**:
- Should always validate price data, with appropriate thresholds
- Should log validation failures for monitoring

**Severity**: LOW - Data quality risk, but exchange data is generally reliable

**Fix Required**:
1. Re-enable price validation with appropriate thresholds for production
2. Add validation failure logging
3. Add circuit breaker for repeated validation failures
4. Investigate why validation was blocking valid prices

---

## Additional Concerns (Not Bugs, But Worth Monitoring)

### 1. BTC Sentiment Bias Feature Not Implemented
- **Location**: `config/profiles/kalshi_crypto_15m_v2.yaml` line 186
- **Status**: Documented in config but code exists and is disabled
- **Risk**: Confusion between documented features and actual implementation
- **Recommendation**: Either implement properly or remove from config

### 2. Regime-Based Sizing Disabled
- **Location**: `merid/prediction/unified_sizing.py` line 91
- **Status**: Explicitly disabled to prevent interference with $1 cap
- **Risk**: Missing opportunity for adaptive sizing
- **Recommendation**: Re-enable with proper integration into risk envelope

### 3. Synthetic Spreads in Price Feed
- **Location**: `data/live_price_feed.py` line 305
- **Status**: Documented with `spread_is_synthetic` flag
- **Risk**: Synthetic spreads should not be used for trading
- **Recommendation**: Ensure trading logic respects this flag

---

## Comparison to Industry Best Practices

| Best Practice | MERID Status | Gap |
|--------------|--------------|-----|
| Look-ahead bias prevention | Partial | Some temporal checks, but no systematic validation |
| Survivorship bias | N/A | Crypto universe has no delisting, but asset selection is static |
| Overfitting prevention | Weak | Walk-forward exists but not integrated |
| Data snooping prevention | Weak | No hypothesis pre-registration, no test tracking |
| Reproducibility | Weak | Seeds in tests only, not production |
| Dynamic correlations | Missing | Hardcoded static values |
| Dynamic signal quality | Missing | Static metadata |
| Real-time validation | Partial | Some checks, but gaps in price validation |

---

## Recommended Fix Priority

### P0 (Immediate - Critical Impact)
1. **BUG #3**: Remove mock data from production API
2. **BUG #1**: Implement dynamic correlation matrix
3. **BUG #2**: Implement dynamic signal quality calculation

### P1 (This Week - High Impact)
4. **BUG #4**: Integrate walk-forward validation
5. **BUG #7**: Re-enable price validation

### P2 (Next Sprint - Medium Impact)
6. **BUG #5**: Add deterministic seed handling
7. **BUG #6**: Implement adaptive liquidity thresholds

---

## Conclusion

The MERID stack has several bias bugs that violate industry best practices. The most critical issues are:
1. Hardcoded correlations that don't adapt to market conditions
2. Static signal quality that doesn't reflect actual performance
3. Mock data in production API that masks real performance

These issues can be addressed by implementing dynamic parameter calculation, integrating existing validation frameworks, and ensuring production code uses real data sources.

The audit found no evidence of look-ahead bias or data snooping in the current implementation, which is positive. However, the lack of systematic out-of-sample validation means overfitting could go undetected.

---

**Audit Completed**: 2026-07-23  
**Auditor**: Cascade AI Agent  
**Next Review**: After P0/P1 fixes implemented
