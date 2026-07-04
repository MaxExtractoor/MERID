# Maker-Taker Decision Audit Report
**Date:** 2026-07-02  
**Scope:** End-to-end audit of maker-taker decision pipeline for 15m crypto prediction markets  
**Assets:** BTC, ETH, SOL, XRP, DOGE

---

## Executive Summary

**Critical Finding:** Price guard inconsistency found in `order_router.py` - minimum price validation was set to 5¢ instead of 15¢, creating a potential bypass path for low-priced trades. This has been fixed to align with the global 15¢ price guard.

**Overall Assessment:** The maker-taker pipeline is well-architected with proper fee calculations, risk checks, and per-asset parameter tuning. The system aligns with industry best practices for prediction market trading.

---

## 1. Upstream: Signal Generation and Edge Calculation

### Location: `merid/prediction/agent_grid_15m.py`

**Edge Calculation Logic:**
- **YES Buy:** `edge_pct = (buy_threshold - market_price) / buy_threshold * 100`
- **NO Buy:** `edge_pct = (market_price - sell_threshold) / (1.0 - sell_threshold) * 100`
- **Base Edge:** 2% minimum edge at threshold crossing
- **Dynamic Confidence:** `confidence = min(0.99, 0.50 + 2.0 * distance_from_threshold)`

**Price Clamping (FIXED):**
- **Issue:** Price clamping was using 5¢ minimum instead of 15¢
- **Fix Applied:** Changed all price clamping from 5¢ to 15¢ in `_generate_signal` method
- **Lines Modified:** 2688-2694, 2704-2712, 2718-2730, 2734-2746, 2751-2752
- **Impact:** Prevents trades below 15¢ from executing, aligning with global price guard

**Status:** ✅ FIXED - Price clamping now enforces 15¢ minimum consistently

---

## 2. Midstream: Order Routing and Risk Checks

### Location: `merid/event_venues/kalshi/order_router.py`

**Maker-Taker Policy Application:**
- **Function:** `apply_maker_taker_policy(intent)` called before risk checks
- **Policy Mode:** `AGGRESSIVE_CONVICTION` (default for 15m crypto)
- **Decision Logic:** Uses edge_pct to determine maker vs taker role
- **Fee Calculation:** Parabolic fee formula applied to estimate net edge

**CRITICAL BUG FOUND AND FIXED:**
- **Location:** `_check_intent_risk()` function, line 1616
- **Issue:** Price range validation was `if intent.price_cents < 5 or intent.price_cents > 70`
- **Fix:** Changed to `if intent.price_cents < 15 or intent.price_cents > 70`
- **Impact:** This was a second bypass path for 5¢ trades - now blocked

**Risk Checks:**
1. Global rate limiting (30 orders/minute)
2. Position limits (per-asset notional caps)
3. Asset notional validation
4. Side/action validation
5. Signal metadata validation (edge, confidence, model_prob)

**Status:** ✅ FIXED - Price validation now enforces 15¢ minimum

---

## 3. Downstream: Execution and Fee Calculation

### Location: `merid/event_venues/kalshi/parabolic_fees.py`

**Fee Formula (Kalshi Parabolic):**
- **Taker Fee:** `fee_cents = ceil(0.07 * C * P * (1 - P))`
  - Maximum: 1.75¢ per contract at P = 0.5
- **Maker Fee:** `fee_cents = ceil(0.0175 * C * P * (1 - P))`
  - Maximum: 0.4375¢ per contract at P = 0.5
- **Maker/Taker Ratio:** Maker fee is exactly 25% of taker fee

**Implementation Quality:**
- Uses Decimal arithmetic for precision
- Proper ceiling rounding (never floor/round)
- Price validation and clamping to [0.01, 0.99] range
- Handles invalid inputs gracefully (returns 0)

**Status:** ✅ ALIGNED - Fee calculation matches Kalshi specification

### Location: `merid/event_venues/kalshi/client.py`

**Final Safety Net:**
- **GlobalExecutionGuard:** Final check before API call
- **Price Guard:** 15¢ minimum enforced at line 1966
- **Validation:** Zero/negative price rejection
- **Self-Trade Prevention:** "taker_at_cross" mode enabled

**Status:** ✅ SECURE - Multiple layers of protection

---

## 4. Maker-Taker Policy Engine

### Location: `merid/event_venues/kalshi/maker_taker_policy.py`

**Policy Modes:**
- **NEUTRAL_MM:** Maker-only, never cross spread
- **AGGRESSIVE_CONVICTION:** Take liquidity when edge >> fees + threshold (default)
- **ARB_LEG:** Prefer taker for speed, verify net PnL positive

**Thresholds:**
- **AGGRESSIVE_THRESHOLD_PCT:** 5.0% (edge required to take liquidity)
- **ARB_MIN_EDGE_PCT:** 0.5% (minimum for arbitrage legs)

**Decision Logic:**
- Calculates both taker and maker fees
- Determines if order crosses spread
- Returns role decision with fee estimates and net edge

**Status:** ✅ ALIGNED - Thresholds are conservative and appropriate

### Location: `merid/event_venues/kalshi/maker_taker_integration.py`

**TEMPORARY OVERRIDES (Noted for Review):**
- Lines 102-113: Maker-taker policy is temporarily forced to taker mode
- Post-only flag disabled
- Maker price adjustment disabled (to avoid float contamination)
- **Impact:** System is currently operating in taker-only mode, not benefiting from maker rebates

**Recommendation:** Review and remove temporary overrides once float handling is resolved

**Status:** ⚠️ TEMPORARY - Maker optimization disabled

---

## 5. Industry Research Comparison

### Polymarket (Decentralized)
- **Taker Fees:** Dynamic, up to 1.80% on 15-minute crypto markets
- **Maker Rebates:** 50% in Finance, 25% in Politics/Tech
- **Philosophy:** Fee redistribution to incentivize liquidity
- **Advantage:** Higher global liquidity, 5-7% better effective return for high-volume

### Kalshi (CFTC-Regulated)
- **Taker Fees:** Parabolic formula, max 1.75¢ per contract
- **Maker Fees:** Parabolic formula, max 0.4375¢ per contract
- **Philosophy:** Fixed fee per contract, predictable costs
- **Advantage:** Regulatory clarity, US market access

### Our Implementation
- **Fee Calculation:** ✅ Matches Kalshi parabolic formula exactly
- **Policy Engine:** ✅ Implements maker-taker decision logic
- **Thresholds:** ✅ Conservative (5% aggressive threshold)
- **Asset Tuning:** ✅ Per-asset parameters based on volatility research

**Status:** ✅ ALIGNED - Implementation matches Kalshi specification

---

## 6. Per-Asset Parameter Analysis

### Volatility Profile (April 2026 Research)
| Asset | Volatility | Beta to BTC | Correlation to BTC |
|-------|-----------|-------------|-------------------|
| BTC   | 28.7%     | 1.0         | 1.00              |
| ETH   | 45.2%     | 1.65        | 0.87              |
| SOL   | 89.6%     | 2.30        | 0.79              |
| XRP   | ~55%      | 1.35        | -                 |
| DOGE  | ~100%     | 2.70        | 0.71              |

### Current Configuration (kalshi_crypto_15m_v2.yaml)

**BTC (Tier 1 - Core):**
- Min Edge: 3% (early/mid/late), 4% (terminal)
- Max Distance: 1.5%
- Max Contracts: 2
- Max Notional: 5% of capital
- ✅ Appropriate for stable, liquid asset

**ETH (Tier 1 - Core):**
- Min Edge: 3% (early/mid/late), 4% (terminal)
- Max Distance: 1.8%
- Max Contracts: 2
- Max Notional: 5% of capital
- ✅ Appropriate for declining volatility (L2 scaling)

**SOL (Tier 2 - Alt):**
- Min Edge: 5% (early/mid/late), 6% (terminal)
- Max Distance: 2.5%
- Max Contracts: 2
- Max Notional: 5% of capital
- ✅ Appropriate for high volatility (89.6% vol, beta 2.30)

**XRP (Tier 2 - Alt):**
- Min Edge: 4% (early/mid/late), 5% (terminal)
- Max Distance: 2.5%
- Max Contracts: 2
- Max Notional: 5% of capital
- ✅ Appropriate for event-driven asset

**DOGE (Tier 2 - Alt):**
- Min Edge: 5% (early/mid/late), 6% (terminal)
- Max Distance: 3.0%
- Max Contracts: 2
- Max Notional: 5% of capital
- ✅ Appropriate for most volatile asset (100% vol, beta 2.70)

**Status:** ✅ WELL-TUNED - Parameters align with volatility research

---

## 7. High Leverage Bugs Found

### Bug #1: Price Clamping Minimum (FIXED)
- **Location:** `agent_grid_15m.py` lines 2688-2752
- **Issue:** Price clamping used 5¢ minimum instead of 15¢
- **Impact:** Allowed 5¢ DOGE NO trade to execute
- **Fix:** Changed all clamping to 15¢ minimum
- **Status:** ✅ FIXED

### Bug #2: Order Router Price Validation (FIXED)
- **Location:** `order_router.py` line 1616
- **Issue:** Price validation used 5¢ minimum instead of 15¢
- **Impact:** Second bypass path for low-priced trades
- **Fix:** Changed validation to 15¢ minimum
- **Status:** ✅ FIXED

### Issue #3: Maker-Taker Temporarily Disabled (NOTED)
- **Location:** `maker_taker_integration.py` lines 102-113
- **Issue:** Maker optimization temporarily forced to taker mode
- **Impact:** Not benefiting from maker rebates (25% of taker fee)
- **Recommendation:** Review and remove once float handling resolved
- **Status:** ⚠️ TEMPORARY - Needs review

---

## 8. Recommendations

### Immediate Actions (Completed)
1. ✅ Fix price clamping minimum to 15¢ in `agent_grid_15m.py`
2. ✅ Fix price validation minimum to 15¢ in `order_router.py`
3. ✅ Add test for 15¢ minimum price clamping
4. ✅ Run all profile fixes tests to verify no regressions

### Short-Term Actions
1. **Review Maker-Taker Overrides:** Remove temporary taker-only mode in `maker_taker_integration.py` once float handling is resolved
2. **Add Integration Test:** Test end-to-end order flow with maker role to ensure price adjustment works correctly
3. **Monitor Fee Impact:** Track maker vs taker execution ratio to optimize for fee savings

### Long-Term Actions
1. **Dynamic Thresholds:** Consider adjusting `AGGRESSIVE_THRESHOLD_PCT` per asset based on volatility
2. **Maker Rebate Tracking:** Implement tracking of fee savings from maker placement
3. **Spread Analysis:** Add spread monitoring to identify optimal maker/taker timing

---

## 9. Conclusion

The maker-taker decision pipeline is well-architected with proper layering:
- **Upstream:** Edge calculation and price clamping ✅
- **Midstream:** Risk checks and policy application ✅
- **Downstream:** Fee calculation and final safety nets ✅

**Critical bugs fixed:** Two price guard bypass paths (5¢ minimum) have been corrected to 15¢ minimum, aligning with the global price guard and preventing future low-priced trades.

**Per-asset parameters:** Well-tuned based on 2026 volatility research, with appropriate edge thresholds and distance filters for each asset's volatility profile.

**Industry alignment:** Fee calculation matches Kalshi's parabolic formula exactly. Policy engine thresholds are conservative and appropriate for 15m crypto markets.

**Overall Status:** ✅ SECURE - System is properly aligned with industry best practices and research benchmarks.
