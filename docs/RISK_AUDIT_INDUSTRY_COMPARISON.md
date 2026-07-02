# Risk Audit: Industry Best Practices Comparison

**Date:** 2026-06-28  
**Purpose:** Compare MERID's risk controls against industry best practices for algorithmic trading systems

## Executive Summary

This audit compares MERID's current risk management implementation against industry best practices from regulatory bodies (FIA, FCA, EU Delegated Regulation) and leading quantitative trading firms. Key findings and recommendations are documented below.

## Industry Best Practices (Source: FIA, FCA, EU Regulation, Quant Firms)

### 1. Pre-Trade Controls

**Industry Standard:**
- Maximum order size (fat-finger limits)
- Maximum intraday position limits
- Leverage limits
- Exposure caps per instrument/asset class
- Credit/margin checks
- Permission validation

**MERID Implementation:**
- ✅ `max_order_size_usd` exists in settings
- ✅ `max_position_usd_per_symbol` in RiskGuard
- ✅ `max_leverage: 3.0` standardized across codebase
- ✅ `max_total_exposure_usd` in RiskGuard
- ✅ Permission model in RiskGuard
- ⚠️ **GAP:** No explicit fat-finger limit validation in order submission path

### 2. Post-Trade Controls

**Industry Standard:**
- Real-time monitoring of positions and P&L
- Daily loss limits with automatic halts
- Maximum drawdown limits (15-25% for hedge funds)
- Portfolio reconciliation
- Market abuse surveillance

**MERID Implementation:**
- ✅ Daily loss limits in kill_switches.py
- ✅ Drawdown tiers: 10% (normal), 12% (reduced), 15% (critical), halt
- ✅ Real-time P&L tracking
- ✅ Kill switch persistence
- ⚠️ **GAP:** Drawdown limits are configurable but not stress-tested against historical crises

### 3. Position Sizing

**Industry Standard:**
- Volatility-adjusted sizing (ATR-based)
- Drawdown-adjusted sizing (reduce during drawdowns)
- Correlation-adjusted sizing (reduce on correlated positions)
- Fixed fractional with risk per trade (1-2%)
- Maximum exposure limits across all strategies

**MERID Implementation:**
- ✅ Volatility-based sizing in position_sizing.py
- ✅ Kelly criterion (documented as heuristic)
- ✅ Fixed fractional sizing
- ✅ Risk parity sizing
- ✅ Correlation matrix in portfolio risk calculation
- ⚠️ **GAP:** No drawdown-adjusted sizing (positions don't auto-reduce during drawdowns)
- ⚠️ **GAP:** Correlation matrix lookup failures were silent (FIXED in this audit)
- ⚠️ **GAP:** Position-aware sizing used stale price data (FIXED in this audit)

### 4. Circuit Breakers & Kill Switches

**Industry Standard:**
- Immediate kill switches for catastrophic scenarios
- Graduated circuit breakers (warning → reduce → halt)
- Per-asset and global kill switches
- Manual operator override capability
- Automatic triggering on limit breaches

**MERID Implementation:**
- ✅ Global kill switch in kill_switches.py
- ✅ Daily loss kill switch
- ✅ Per-market kill switches
- ✅ Manual emergency_stop() function
- ✅ Graduated drawdown tiers (5%/8%/12% in formulas, 10%/12%/15%/halt in config)
- ✅ Kill switch persistence to disk
- ✅ Prometheus metrics for kill switch events

### 5. Monitoring & Surveillance

**Industry Standard:**
- Real-time risk dashboards
- Alert generation on limit breaches
- Market abuse detection
- System health monitoring
- Error rate tracking

**MERID Implementation:**
- ✅ Grafana dashboards
- ✅ Prometheus metrics
- ✅ Alertmanager integration
- ✅ WebSocket streaming for real-time updates
- ✅ Error classification in error_classification.py
- ⚠️ **GAP:** No explicit market abuse surveillance system

### 6. Stress Testing & Backtesting

**Industry Standard:**
- Historical crisis scenario testing
- Correlation regime monitoring
- Stress testing under extreme conditions
- Regular backtesting of strategies
- Model validation

**MERID Implementation:**
- ✅ Backtesting engine in backtesting/
- ✅ Chaos engineering tests in tests/chaos/
- ✅ Stress scenarios in test_kalshi_stress_scenarios.py
- ⚠️ **GAP:** No systematic historical crisis scenario testing (e.g., 2008, COVID-19 crash)
- ⚠️ **GAP:** Correlation regime monitoring not automated

## Identified Risky/Dangerous Patterns

### P0 - Critical Risks

1. **No Fat-Finger Limit Validation in Order Path**
   - **Risk:** Accidental large orders could be submitted
   - **Location:** Order submission in execution layer
   - **Recommendation:** Add explicit max_order_size check before every order submission

2. **No Drawdown-Adjusted Position Sizing**
   - **Risk:** System continues full-size positions during drawdowns, accelerating losses
   - **Location:** position_sizing.py, unified_sizing.py
   - **Recommendation:** Implement drawdown-based position scaling (reduce size as drawdown increases)

3. **No Historical Crisis Stress Testing**
   - **Risk:** System may fail under extreme market conditions not seen in recent data
   - **Location:** backtesting/, stress testing
   - **Recommendation:** Add systematic testing against historical crises (2008, 2020 COVID, etc.)

### P1 - High Risks

4. **Correlation Matrix Not Dynamically Updated**
   - **Risk:** Static correlation matrix may not reflect current market conditions
   - **Location:** position_sizing.py
   - **Recommendation:** Implement rolling correlation calculation (e.g., 30-day window)

5. **No Volatility Regime Filters**
   - **Risk:** System may trade aggressively during high volatility periods
   - **Location:** signal generation, position sizing
   - **Recommendation:** Add volatility regime detection (low/normal/high) with adjusted sizing

6. **No Cross-Strategy Correlation Monitoring**
   - **Risk:** Multiple strategies may become correlated simultaneously, creating hidden concentration
   - **Location:** portfolio management
   - **Recommendation:** Monitor and limit aggregate exposure when cross-strategy correlation increases

### P2 - Medium Risks

7. **Market Abuse Surveillance Missing**
   - **Risk:** System may inadvertently engage in market manipulative behavior
   - **Location:** surveillance layer
   - **Recommendation:** Implement market abuse pattern detection (spoofing, layering, etc.)

8. **Rate Limiting Not Centralized**
   - **Risk:** Inconsistent rate limiting across different API endpoints
   - **Location:** Multiple API files
   - **Recommendation:** Centralize rate limiting middleware

9. **No Automated Recovery from Kill Switches**
   - **Risk:** Manual intervention required to resume trading after legitimate halt
   - **Location:** kill_switches.py
   - **Recommendation:** Add configurable auto-recovery with manual approval

## Comparison Summary

| Control | Industry Standard | MERID Status | Gap |
|---------|------------------|--------------|-----|
| Max Order Size | Required | Partial | P0 |
| Intraday Position Limits | Required | ✅ | - |
| Leverage Limits | Required | ✅ | - |
| Daily Loss Limits | Required | ✅ | - |
| Drawdown Limits | Required (15-25%) | ✅ (10-15%) | - |
| Volatility-Adjusted Sizing | Best Practice | ✅ | - |
| Drawdown-Adjusted Sizing | Best Practice | ❌ | P0 |
| Correlation-Adjusted Sizing | Best Practice | Partial | P1 |
| Fat-Finger Limits | Required | Partial | P0 |
| Kill Switches | Required | ✅ | - |
| Circuit Breakers | Required | ✅ | - |
| Stress Testing | Required | Partial | P0 |
| Market Abuse Surveillance | Required | ❌ | P2 |
| Real-time Monitoring | Required | ✅ | - |
| Error Classification | Best Practice | ✅ | - |

## Recommendations Priority

### Immediate (P0)
1. Implement fat-finger limit validation in order submission path
2. Add drawdown-adjusted position sizing
3. Implement historical crisis stress testing suite

### Short-term (P1)
4. Implement dynamic correlation matrix updates
5. Add volatility regime filters
6. Implement cross-strategy correlation monitoring

### Medium-term (P2)
7. Add market abuse surveillance
8. Centralize rate limiting
9. Add automated kill switch recovery

## Conclusion

MERID has a solid foundation of risk controls that align with many industry best practices. The kill switch implementation, daily loss limits, and graduated drawdown tiers are well-designed. However, there are critical gaps in fat-finger protection, drawdown-adjusted sizing, and stress testing that should be addressed to bring the system to industry-leading standards.

The fixes implemented in this audit (leverage standardization, silent exception handling, stale price data fix) have improved the system's reliability. The remaining P0 items should be prioritized for immediate implementation.
