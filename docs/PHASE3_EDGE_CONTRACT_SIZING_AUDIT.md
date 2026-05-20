# Phase 3: Edge/Contract/Sizing Audit

**Date:** 2026-05-12  
**Scope:** MERID Kalshi Trading System (15m BTC/ETH/SOL/XRP/DOGE)  
**Purpose:** Validate venue specs registry, sizing correctness, portfolio limits, and drawdown limits

---

## Executive Summary

This document defines validation checks for edge/contract/sizing correctness. All venue specifications must be in a centralized registry, position sizing must be correct and deterministic, portfolio limits must be enforced, and drawdown limits must be properly calculated and enforced.

---

## Venue Specs Registry

### Requirement 1: Centralized Venue Specifications

**Statement:** All venue-specific specifications (min/max sizes, fees, tick sizes, etc.) must be in a centralized registry, not scattered throughout the codebase.

**Current Implementation:**
- `merid/event_venues/kalshi/risk_parameters.py` - Centralized Kalshi risk parameters
- `merid/event_venues/kalshi/fees.py` - Fee calculation module
- `merid/event_venues/kalshi/types.py` - Domain types
- Some parameters still scattered in config files

**Validation:**
- All Kalshi-specific constants must be in `risk_parameters.py`
- All fee calculations must use the unified fees module
- No magic numbers in trading logic
- All size thresholds must come from named constants

**Enforcement Point:** Code review, static analysis

**Violation Action:** Refactor to use centralized constants, add missing constants to registry

---

### Requirement 2: Venue Specs Versioning

**Statement:** Venue specifications must be versioned to track changes and enable rollback.

**Current Implementation:**
- No explicit versioning in `risk_parameters.py`
- Changes tracked via git but not in runtime

**Validation:**
- Add version constant to `risk_parameters.py`
- Log version on startup
- Alert on version mismatch between runs

**Enforcement Point:** Startup validation

**Violation Action:** Add version tracking, alert on mismatch

---

### Requirement 3: Venue Specs Validation

**Statement:** Venue specifications must be validated for consistency and correctness on startup.

**Method:**
- Check min/max size consistency (min < max)
- Check fee rates are positive and reasonable
- Check probability bounds are valid (0-1)
- Check edge thresholds are positive
- Check bankroll fractions are valid (0-1)

**Thresholds:**
- Min size < Max size
- Fee rate > 0 and < 0.10 (10%)
- Probability bounds: 0 <= min < max <= 1
- Edge threshold > 0
- Bankroll fraction > 0 and < 1

**Enforcement Point:** Startup validation

**Violation Action:** Log error, fail startup if critical inconsistency

---

## Sizing Correctness

### Requirement 1: Kelly Criterion Correctness

**Statement:** Kelly criterion calculations must be mathematically correct and deterministic.

**Current Implementation:**
- `kelly_fraction_for_binary()` in `position_sizer.py` implements: `f = (p * b - q) / b`
- `adaptive_kelly_fraction()` adds shrinkage based on PF, drawdown, volatility
- `vol_scaled_fraction()` provides continuous volatility scaling
- `atr_risk_fraction()` for ATR-based sizing

**Validation:**
- Kelly formula: `f = (p * b - q) / b` where `b = win_payout / loss_amount`
- For binary: `win_payout = 100 - price_cents`, `loss_amount = price_cents`
- Kelly fraction must be in range [0, 1]
- Adaptive shrinkage must not increase fraction
- Vol scaling must be deterministic

**Enforcement Point:** Unit tests, invariant checks

**Violation Action:** Log error, reject trade if Kelly invalid

---

### Requirement 2: Fee Calculation Correctness

**Statement:** Fee calculations must be correct and use the proper tiered fee schedule.

**Current Implementation:**
- `calculate_kalshi_fee_cents()` in fees module
- Tiered fee rates: 7% (<100 contracts), 5% (100-1000), 3% (>1000)
- Formula: `ceil(0.07 * contracts * price_cents * (1 - price_cents/100))`

**Validation:**
- Fee calculation matches Kalshi documentation
- Tier boundaries are correct
- Fee per contract decreases with volume
- Total fee is non-decreasing with contract count

**Thresholds:**
- Fee per contract: 0-7 cents (at P=0.5)
- Total fee: 0-700 cents (100 contracts at P=0.5)
- Fee rate: 3-7% depending on tier

**Enforcement Point:** Unit tests, integration tests

**Violation Action:** Log error, alert operator, fix fee calculation

---

### Requirement 3: Size Cap Enforcement

**Statement:** All position sizes must be capped by configured limits.

**Current Implementation:**
- `SIZER_MIN_CONTRACTS = 1`
- `SIZER_MAX_CONTRACTS = 50`
- `SIZER_MAX_BANKROLL_PCT = 0.05` (5%)
- `SIZER_MAX_CONTRACTS_PER_UNDERLYING_PER_HOUR = 100`

**Validation:**
- Contract count >= min_contracts
- Contract count <= max_contracts
- Position value <= max_bankroll_pct * bankroll
- Per-underlying hourly exposure <= max_contracts_per_underlying_per_hour

**Enforcement Point:** Position sizer runtime check

**Violation Action:** Clamp to limits, log warning

---

### Requirement 4: Sizing Determinism

**Statement:** Position sizing must be deterministic given the same inputs.

**Current Implementation:**
- `PositionSizer.compute()` uses deterministic formulas
- Some runtime state: `_manual_override_factor`, `_realized_vol`, `_atr_value`
- Sentiment/vol multiplier from external service

**Validation:**
- Same inputs (edge_pct, price_cents, bankroll, PF, etc.) produce same output
- No randomness in sizing calculations
- Timestamps not used in sizing (except for logging)
- External multiplier lookup is deterministic

**Enforcement Point:** Unit tests, offline recompute

**Violation Action:** Refactor to pure functions, isolate state

---

## Portfolio Limits

### Requirement 1: Per-Market Exposure Cap

**Statement:** Total exposure per market must be capped at configured percentage.

**Current Implementation:**
- `PER_MARKET_EXPOSURE_CAP_PCT = 0.05` (5%) in risk_parameters.py
- Not explicitly enforced in current code

**Validation:**
- Sum of open positions for a market <= per_market_exposure_cap_pct * bankroll
- Check before opening new position
- Check on position lifecycle (positions may settle)

**Thresholds:**
- Per-market exposure: <= 5% of bankroll
- Alert at 4% (80% of cap)
- Block at 5% (hard cap)

**Enforcement Point:** Pre-trade risk check, position lifecycle check

**Violation Action:** Block trade, log warning, alert operator

---

### Requirement 2: Per-Strategy Exposure Cap

**Statement:** Total exposure per strategy must be capped at configured percentage.

**Current Implementation:**
- `PER_STRATEGY_EXPOSURE_CAP_PCT = 0.05` (5%) in risk_parameters.py
- Not explicitly enforced in current code

**Validation:**
- Sum of open positions for a strategy <= per_strategy_exposure_cap_pct * bankroll
- Check before opening new position
- Check on position lifecycle

**Thresholds:**
- Per-strategy exposure: <= 5% of bankroll
- Alert at 4% (80% of cap)
- Block at 5% (hard cap)

**Enforcement Point:** Pre-trade risk check, position lifecycle check

**Violation Action:** Block trade, log warning, alert operator

---

### Requirement 3: Venue Exposure Cap

**Statement:** Total exposure on a venue must be capped at configured percentage.

**Current Implementation:**
- `VENUE_EXPOSURE_CAP_PCT = 0.20` (20%) in risk_parameters.py
- Not explicitly enforced in current code

**Validation:**
- Sum of open positions on venue <= venue_exposure_cap_pct * bankroll
- Check before opening new position
- Check on position lifecycle

**Thresholds:**
- Venue exposure: <= 20% of bankroll
- Alert at 16% (80% of cap)
- Block at 20% (hard cap)

**Enforcement Point:** Pre-trade risk check, position lifecycle check

**Violation Action:** Block trade, log warning, alert operator

---

### Requirement 4: Concentration Risk Check

**Statement:** Portfolio concentration must be monitored and limited.

**Method:**
- Calculate Herfindahl-Hirschman Index (HHI) for portfolio
- HHI = sum(squared position weights)
- Alert if HHI exceeds threshold

**Thresholds:**
- HHI < 0.25: Well-diversified
- HHI 0.25-0.50: Moderate concentration
- HHI > 0.50: High concentration (alert)

**Enforcement Point:** Portfolio risk calculation (hourly)

**Violation Action:** Log warning, alert operator, consider position reduction

---

## Drawdown Limits

### Requirement 1: Maximum Drawdown Limit

**Statement:** Maximum drawdown must be enforced at configured percentage.

**Current Implementation:**
- `MAX_DRAWDOWN_PCT = 0.15` (15%) in risk_parameters.py
- Drawdown calculation in `merid/formulas.py`
- Kill switch in `risk/kill_switches.py` uses daily loss limit

**Validation:**
- Drawdown = (peak - current) / peak
- Drawdown must be calculated from equity curve
- Drawdown limit enforced via kill switch
- Separate daily loss limit (10%) from max drawdown (15%)

**Thresholds:**
- Max drawdown: 15%
- Warning at 10% (67% of limit)
- Kill switch at 15% (hard limit)

**Enforcement Point:** Drawdown monitor (every 5 minutes), kill switch

**Violation Action:** Trigger kill switch, alert operator, halt trading

---

### Requirement 2: Daily Loss Limit

**Statement:** Daily loss must be limited to configured percentage.

**Current Implementation:**
- `DAILY_LOSS_LIMIT_PCT = 0.10` (10%) in risk_parameters.py
- `daily_loss_limit` in `RiskController` (derived from settings)
- Daily PnL tracked in fills_ledger
- Kill switch triggers when daily loss >= limit

**Validation:**
- Daily PnL calculated from fills_ledger (canonical source)
- Daily loss limit = daily_loss_limit_pct * bankroll
- Daily PnL resets at midnight UTC
- Kill switch triggers when daily PnL <= -daily_loss_limit

**Thresholds:**
- Daily loss limit: 10% of bankroll
- Warning at 8% (80% of limit)
- Kill switch at 10% (hard limit)

**Enforcement Point:** `RiskController.can_trade()` (every trade), fills_ledger sync

**Violation Action:** Trigger kill switch, alert operator, halt trading

---

### Requirement 3: Cycle Drawdown Limit

**Statement:** 15-minute cycle drawdown must be monitored and used for de-risking.

**Current Implementation:**
- `cycle_drawdown.py` implements cycle drawdown manager
- `get_cycle_risk_multiplier()` returns multiplier (0-1)
- Multiplier applied in `PositionSizer.compute()`

**Validation:**
- Cycle drawdown calculated over rolling 15-minute window
- Risk multiplier decreases as drawdown increases
- Multiplier range: 0.25 (severe) to 1.0 (normal)
- Applied multiplicatively to position size

**Thresholds:**
- Cycle drawdown < 5%: multiplier = 1.0
- Cycle drawdown 5-10%: multiplier = 0.75
- Cycle drawdown 10-15%: multiplier = 0.50
- Cycle drawdown > 15%: multiplier = 0.25

**Enforcement Point:** Position sizer (every trade)

**Violation Action:** Reduce position size, log warning

---

### Requirement 4: Drawdown Calculation Correctness

**Statement:** Drawdown calculations must be mathematically correct and use the right data source.

**Current Implementation:**
- Drawdown formula in `merid/formulas.py`
- Uses equity from fills_ledger
- Peak tracking in separate module

**Validation:**
- Drawdown = (peak_equity - current_equity) / peak_equity
- Peak equity must be from equity curve (not just daily high)
- Current equity from fills_ledger (canonical source)
- No double-counting of unrealized vs realized

**Enforcement Point:** Unit tests, invariant checks

**Violation Action:** Log error, alert operator, fix calculation

---

## Automated Test Plan

### Test Suite: `tests/risk/test_edge_contract_sizing_audit.py`

**Test Classes:**

1. `TestVenueSpecsRegistry`
   - Test: all specs centralized in risk_parameters.py
   - Test: no magic numbers in trading logic
   - Test: specs versioning
   - Test: specs validation on startup
   - Test: specs consistency (min < max, etc.)

2. `TestKellyCriterionCorrectness`
   - Test: kelly_fraction_for_binary formula
   - Test: Kelly fraction in range [0, 1]
   - Test: adaptive_kelly_fraction shrinkage
   - Test: vol_scaled_fraction determinism
   - Test: atr_risk_fraction calculation

3. `TestFeeCalculationCorrectness`
   - Test: fee calculation matches Kalshi docs
   - Test: tier boundaries correct
   - Test: fee per contract decreases with volume
   - Test: total fee non-decreasing with contract count
   - Test: edge cases (price=0, price=100)

4. `TestSizeCapEnforcement`
   - Test: min_contracts enforced
   - Test: max_contracts enforced
   - Test: max_bankroll_pct enforced
   - Test: per_underlying_hourly_cap enforced
   - Test: clamping behavior

5. `TestSizingDeterminism`
   - Test: same inputs produce same output
   - Test: no randomness in sizing
   - Test: timestamps not used in sizing
   - Test: external multiplier deterministic
   - Test: offline recompute matches live

6. `TestPortfolioLimits`
   - Test: per_market_exposure_cap enforced
   - Test: per_strategy_exposure_cap enforced
   - Test: venue_exposure_cap enforced
   - Test: concentration risk (HHI) calculation
   - Test: limit alerts

7. `TestDrawdownLimits`
   - Test: max_drawdown_limit enforced
   - Test: daily_loss_limit enforced
   - Test: cycle_drawdown_multiplier applied
   - Test: drawdown calculation correctness
   - Test: kill switch triggers correctly

8. `TestRiskParametersConsistency`
   - Test: all risk parameters defined
   - Test: parameter values reasonable
   - Test: no contradictions between parameters
   - Test: parameter changes tracked
   - Test: parameter validation

9. `TestPositionSizerIntegration`
   - Test: compute() with valid inputs
   - Test: compute() with invalid inputs
   - Test: compute() with zero edge
   - Test: compute() with negative edge
   - Test: compute() with size_factor=0 (halt)

**Total Target:** 80+ edge/contract/sizing tests

---

## Implementation Roadmap

### Step 1: Document Current State (DONE)
- ✅ Identify venue specs registry (risk_parameters.py)
- ✅ Identify position sizer (position_sizer.py)
- ✅ Identify risk controller (kill_switches.py)
- ✅ Identify domain types (types.py)
- ✅ Document current implementation

### Step 2: Define Validation Checks (DONE)
- ✅ Define venue specs registry requirements
- ✅ Define sizing correctness requirements
- ✅ Define portfolio limits requirements
- ✅ Define drawdown limits requirements

### Step 3: Implement Venue Specs Registry Enhancements (NEXT)
- [ ] Add version constant to risk_parameters.py
- [ ] Implement specs validation on startup
- [ ] Add specs consistency checks
- [ ] Add specs change tracking

### Step 4: Implement Sizing Correctness Checks
- [ ] Add Kelly formula validation
- [ ] Add fee calculation validation
- [ ] Add size cap enforcement checks
- [ ] Add sizing determinism tests

### Step 5: Implement Portfolio Limits Enforcement
- [ ] Add per_market_exposure_cap check
- [ ] Add per_strategy_exposure_cap check
- [ ] Add venue_exposure_cap check
- [ ] Add concentration risk monitoring

### Step 6: Implement Drawdown Limits Enforcement
- [ ] Add max_drawdown_limit enforcement
- [ ] Add daily_loss_limit validation
- [ ] Add cycle_drawdown_multiplier validation
- [ ] Add drawdown calculation validation

### Step 7: Implement Test Suite
- [ ] Create `tests/risk/test_edge_contract_sizing_audit.py`
- [ ] Implement all 9 test classes
- [ ] Target: 80+ tests passing
- [ ] Wire into CI pipeline

### Step 8: Add Monitoring and Alerting
- [ ] Add Prometheus metrics for sizing
- [ ] Add alerting for limit breaches
- [ ] Add dashboard for portfolio limits
- [ ] Add dashboard for drawdown monitoring

---

## Success Criteria

Phase 3 is complete when:

1. ✅ This design document is approved
2. [ ] Venue specs registry is versioned and validated on startup
3. [ ] All sizing calculations are validated for correctness
4. [ ] All portfolio limits are enforced
5. [ ] All drawdown limits are enforced
6. [ ] All 80+ edge/contract/sizing tests are implemented and passing
7. [ ] Monitoring and alerting are wired
8. [ ] CI pipeline includes edge/contract/sizing test suite
9. [ ] No sizing errors detected in production
10. [ ] No limit breaches detected in production

---

## References

- `merid/event_venues/kalshi/risk_parameters.py` - Centralized risk parameters
- `merid/event_venues/kalshi/position_sizer.py` - Position sizer
- `merid/risk/position_sizing.py` - General position sizing
- `merid/risk/kill_switches.py` - Risk controller
- `merid/event_venues/kalshi/types.py` - Domain types
- `merid/event_venues/kalshi/fees.py` - Fee calculations
- `merid/formulas.py` - Drawdown formulas
- `merid/event_venues/kalshi/cycle_drawdown.py` - Cycle drawdown manager
- Kalshi API Documentation (v2)

---

**Next Phase:** Phase 4 - Execution layer and Kalshi integration (API validation, latency/slippage profiling, venue health dashboard)
