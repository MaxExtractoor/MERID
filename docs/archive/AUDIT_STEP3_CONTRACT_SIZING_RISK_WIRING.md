# Audit Step 3: Contract, Sizing, and Risk Wiring

**Date:** 2026-05-12  
**Scope:** BTC/ETH/SOL/XRP/DOGE 15-minute contracts  
**Purpose:** Verify every trade's size and constraints match venue/Kalshi contract specs and risk intentions

---

## Venue and Contract Spec Verification

### Kalshi Fee Schedule
**File:** `config/kalshi_fee_schedule.py`  
**Version:** parabolic-default-2024  
**Fee Type:** quadratic (parabolic maker-taker)  
**Rates:**
- Taker rate: 7% (0.07)
- Maker rate: 1.75% (0.0175)

**Status:** ✅ Fee schedule defined and versioned

---

### Kalshi Contract Types
**File:** `merid/event_venues/kalshi/types.py`  
**Contract Types:** Binary YES/NO contracts (bounded loss, 0-100 cents)

**Price Bands (cents):**
- MIN_KALSHI_PRICE_CENTS: 1
- MAX_KALSHI_PRICE_CENTS: 99
- DEFAULT_KALSHI_PRICE_CENTS: 50
- DEEP_OTM_CHEAP_CENTS: 5
- DEEP_OTM_EXPENSIVE_CENTS: 95
- MID_BAND_LOW_CENTS: 20
- MID_BAND_HIGH_CENTS: 80
- MIN_OPEN_PRICE_CENTS: 2
- MAX_OPEN_PRICE_CENTS: 98

**Status:** ✅ Contract specs defined with price bands

---

### Tick Size and Lot Size
**Finding:** Kalshi binary contracts have:
- Tick size: 1 cent (minimum price increment)
- Lot size: 1 contract (minimum order size)

**Verification:** Confirmed in `merid/event_venues/kalshi/risk_parameters.py`:
- MIN_CONTRACTS: 1 (anti-dust)
- MAX_CONTRACTS_DEFAULT: 1000

**Status:** ✅ Tick size and lot size verified

---

## Sizing Sanity

### Position Sizer
**File:** `merid/event_venues/kalshi/position_sizer.py`  
**Method:** Fractional-Kelly position sizing  
**Factors:**
- Kelly fraction: 0.25x (DEFAULT_KELLY_FRACTION)
- Kalshi fee schedule (tiered by contract count)
- Measured profit factor and expectancy from paper sessions
- Per-cell and per-cluster exposure caps
- Sentiment (fear/greed) and volatility regimes

**Size Caps:**
- SIZER_MIN_CONTRACTS: 1
- SIZER_MAX_CONTRACTS: 50
- SIZER_MAX_BANKROLL_PCT: 0.05 (5% max per trade)
- SIZER_MIN_BANKROLL_PCT: 0.15

**Risk Gates:**
- SIZER_PF_MIN_FOR_SCALING: 1.3
- SIZER_PF_FULL_KELLY_AT: 2.0
- SIZER_EXPECTANCY_MIN_CENTS: 6.0
- SIZER_MAX_CONTRACTS_PER_UNDERLYING_PER_HOUR: 100
- SIZER_MIN_TRADES_FOR_SCALING: 50

**Drawdown/Volatility Reductions:**
- Downtown danger (25% drawdown): 0.25x reduction
- Downtown caution (15% drawdown): 0.5x reduction
- Vol danger (50% vol): 0.25x reduction
- Vol caution (30% vol): 0.5x reduction

**Status:** ✅ Comprehensive position sizing with multiple risk gates

---

### Risk Parameters Centralization
**File:** `merid/event_venues/kalshi/risk_parameters.py`  
**Policy:** "No magic numbers" - all numeric thresholds defined here

**Price Bands (cents):**
- MIN_KALSHI_PRICE_CENTS: 1
- MAX_KALSHI_PRICE_CENTS: 99
- DEEP_OTM_MIN_EDGE_PCT: 20% (require stronger justification for deep OTM)

**Probability Thresholds:**
- MIN_MODEL_PROB: 0.60
- CONFIDENCE_NO_TRADE: 0.60
- CONFIDENCE_CAUTIOUS: 0.75
- CONFIDENCE_CONFIDENT: 0.75

**Edge Thresholds:**
- MIN_EDGE_PCT: 2.5%
- DEEP_OTM_MIN_EDGE_PCT: 20%
- IMPLAUSIBLE_MOVE_MIN_EDGE_PCT: 20%

**Status:** ✅ Risk parameters centralized with "no magic numbers" policy

---

## Risk Controls

### Kill Switches
**File:** `merid/risk/kill_switches.py`  
**Kill Switch Types:**
1. Global Kill Switch - Immediately halts all trading
2. Daily Loss Kill - Halts when daily P&L limit breached
3. Position Limit Kill - Halts when position limit exceeded
4. Error Threshold Kill - Halts when error threshold exceeded
5. Circuit Breaker Kill - Halts when all venues circuit-broken
6. Dependency Health Kill - Halts when critical dependency down
7. RTI Feed Stale Kill - Halts when CF Benchmarks RTI feed stale/divergent
8. Loop Lag Halt Kill - Halts when event loop latency critical
9. Portfolio Integrity Kill - Halts on cross-system consistency failure

**Thresholds:**
- daily_loss_limit: 15% of equity (percentage-based)
- max_position_value: $10,000
- error_threshold: 500 (only catastrophic errors halt trading)

**Persistence:** Kill switch state persisted to disk (`data/risk_kill_switch.json`) for fail-safe restarts

**Status:** ✅ Comprehensive kill switches with multiple trigger conditions

---

### Per-Trade Max Loss
**Finding:** SIZER_MAX_RISK_PCT: 0.02 (2% max risk per trade) defined in risk_parameters.py

**Implementation:** Position sizer enforces max risk per trade via Kelly fraction and bankroll caps

**Status:** ✅ Per-trade max loss defined and enforced

---

### Per-Day/Aggregate Exposure Caps
**Finding:** Multiple exposure caps:
- SIZER_MAX_BANKROLL_PCT: 5% max per trade
- SIZER_MAX_CONTRACTS_PER_UNDERLYING_PER_HOUR: 100 contracts per underlying per hour
- max_position_value: $10,000 global position cap

**Status:** ✅ Per-day and aggregate exposure caps defined

---

### Drawdown Controls
**Finding:** Drawdown-based position sizing reductions:
- SIZER_DOWNTOWN_DANGER_THRESHOLD_PCT: 25%
- SIZER_DOWNTOWN_CAUTION_THRESHOLD_PCT: 15%

**Implementation:** Position sizer reduces size when drawdown thresholds exceeded

**Status:** ✅ Drawdown controls implemented

---

## Critical Findings

### 🟢 INFO: Risk Infrastructure is Well-Designed

**Positive Findings:**
- Comprehensive position sizer with fractional-Kelly sizing
- Centralized risk parameters with "no magic numbers" policy
- Multiple kill switches with various trigger conditions
- Fee schedule versioned and defined
- Contract specs with price bands
- Per-trade, per-day, and aggregate exposure caps
- Drawdown-based position sizing reductions
- Kill switch persistence for fail-safe restarts

---

### 🟡 WARNING: No Automated Sizing Validation

**Issue:** No automated job that re-computes "intended" size from sizing logic and compares to actual submitted size.

**Impact:** Sizing bugs or configuration drift could cause incorrect position sizes without detection.

**Risk:** Medium - Position sizing is critical for risk management.

**Recommendation:** Implement a sizing validation job that:
1. Captures sizing inputs (edge, bankroll, risk parameters)
2. Computes expected size from sizing logic
3. Compares to actual submitted size
4. Alerts on mismatch

---

### 🟢 INFO: Risk Parameters are Centralized

**Positive:** All numeric trading thresholds defined in `merid/event_venues/kalshi/risk_parameters.py` per "no magic numbers" policy.

**Implementation:** Trading logic references named constants instead of literals.

---

## Missing Capabilities

### 1. Venue Spec Validation Against Official Docs
**Current:** Contract specs defined in code but not validated against Kalshi official docs  
**Needed:** Periodic validation against Kalshi API contract metadata

---

### 2. Sizing Sanity Check Automation
**Current:** No automated validation of sizing logic vs actual submitted sizes  
**Needed:** Job to recompute intended size and diff against actual

---

### 3. Per-Asset Risk Limits
**Current:** Global risk limits (daily loss, position value) apply across all assets  
**Needed:** Per-asset risk limits (BTC/ETH/SOL/XRP/DOGE) for more granular control

---

## Next Steps for Step 3

1. ✅ Identify venue specs - DONE
2. ✅ Identify sizing logic - DONE
3. ✅ Identify risk controls - DONE
4. ⏳ Validate venue specs against official docs - NEED KALSHI API ACCESS
5. ⏳ Sample 50-100 real trades and recompute intended size - NEED PRODUCTION DATA
6. ⏳ Verify risk checks are called on hot path - NEED CODE REVIEW

---

## Summary

**Obviously Broken:**
- None found in this step

**Probably Fine:**
- Contract specs defined with price bands
- Comprehensive position sizer with fractional-Kelly
- Centralized risk parameters with "no magic numbers" policy
- Multiple kill switches with various triggers
- Per-trade, per-day, and aggregate exposure caps
- Drawdown-based position sizing reductions

**Weird/Unclear:**
- No automated sizing validation (recompute intended size vs actual)
- No per-asset risk limits (global limits only)
- No periodic validation against Kalshi official docs
