# BTC Lifecycle - Corrected Analysis

**Status**: IN PROGRESS - Reconstructing `KXBTC15M-26AUG081315-15` lifecycle

**Correction**: Previous partial matrix had a fundamental arithmetic error. Canonical deltas:
- `outcome_side = no` → -1 YES
- `outcome_side = yes` → +1 YES
- Net: `-1 + 1 = 0` (zero-net exposure, valid NO entry→exit cycle)

---

## Expected Exposure Transitions

```text
before entry:        0
after NO entry:     -1
after YES close:     0
```

---

## Fill 1: fc400f76 (NO Entry)

| Field | Value |
|---|---|
| Timestamp | 2026-08-08T17:02:24.395855Z |
| Market Ticker | KXBTC15M-26AUG081315-15 |
| Fill ID | fc400f76-cfd7-56bb-cfae-98835f10e0e5 |
| Order ID | f8b0af33-399e-44a5-aba6-d44c1f7f85ed |
| Client Order ID | ❌ MISSING |
| Raw API action | sell |
| Raw API side | no |
| Raw API outcome_side | no |
| Raw API book_side | ask |
| Raw API count | 1.00 |
| Raw API no_price | 0.36 |
| Raw API yes_price | 0.64 |
| Canonical signed delta | -1 YES |
| Internal normalized side | no |
| Internal normalized action | buy |
| Internal normalized delta | -1 YES (BUY NO = -YES) |
| Fee | 0.0 |
| Before fill position | ❌ MISSING (need cache) |
| After fill position | ❌ MISSING (need cache) |
| Expected after position | -1 YES |
| Intent kind | ❌ MISSING (need intent logs) |
| Strategy source | ❌ MISSING (need intent logs) |
| Parent position/lot | None (entry) |
| Exit reason | N/A |

---

## Exit Decision

| Field | Value |
|---|---|
| Decision time | 2026-08-08T17:04:02.044119Z (approx, from fill 2) |
| Exit reason | ❌ MISSING (need intent logs) |
| Intent kind | ❌ MISSING (need intent logs) |
| Desired canonical delta | +1 YES (to close -1 YES position) |
| Parent position ID | ❌ MISSING (need cache) |
| Time to market close | ❌ MISSING (need market metadata) |

---

## Fill 2: 56f13022 (YES Close)

| Field | Value |
|---|---|
| Timestamp | 2026-08-08T17:04:02.044119Z |
| Market Ticker | KXBTC15M-26AUG081315-15 |
| Fill ID | 56f13022-737a-7758-aafc-2372b7d90a98 |
| Order ID | 4fff3c00-4920-4c4d-83bb-8bd8d7a1d431 |
| Client Order ID | ❌ MISSING |
| Raw API action | buy |
| Raw API side | yes |
| Raw API outcome_side | yes |
| Raw API book_side | bid |
| Raw API count | 1.00 |
| Raw API no_price | 0.48 |
| Raw API yes_price | 0.52 |
| Canonical signed delta | +1 YES |
| Internal normalized side | no |
| Internal normalized action | sell |
| Internal normalized delta | +1 YES (SELL NO = +YES) |
| Fee | 0.0175 |
| Before fill position | -1 YES (expected) |
| After fill position | 0 (expected) |
| Actual after position | ❌ MISSING (need cache) |
| Intent kind | ❌ MISSING (need intent logs) |
| Strategy source | ❌ MISSING (need intent logs) |
| Parent position/lot | Should reference fc400f76 lot |
| Exit reason | ❌ MISSING (need intent logs) |

---

## Lifecycle Net Result

| Metric | Value |
|---|---|
| Entry fill | fc400f76 @ 17:02:24 (outcome_side=no, delta=-1 YES) |
| Close fill | 56f13022 @ 17:04:02 (outcome_side=yes, delta=+1 YES) |
| Net canonical exposure | 0 (flat) |
| Entry cost | -0.36 USD (paid 36c per NO contract) |
| Close proceeds | +0.52 USD (received 52c per YES contract) |
| Entry fee | 0.0 |
| Close fee | 0.0175 |
| Gross PnL | 0.52 - 0.36 = +0.16 USD |
| Net PnL | 0.16 - 0.0175 = +0.1425 USD |
| Realized PnL (from cache) | ❌ MISSING (need cache) |
| Final position state | ❌ MISSING (need cache) |

---

## Critical Validation Questions

### 1. Cache Position Transition
**Question**: Did the position cache transition exactly `0 → -1 → 0`?

**Required evidence**:
- Cache position before fc400f76: should be 0
- Cache position after fc400f76: should be -1
- Cache position after 56f13022: should be 0

**Status**: ❌ Cannot verify without cache access

### 2. Ledger Delta Consistency
**Question**: Does the internal ledger record canonical deltas consistent with the raw exchange outcome_side?

**Evidence**:
- fc400f76: raw outcome_side=no → -1 YES; internal side=no, action=buy → -1 YES ✅
- 56f13022: raw outcome_side=yes → +1 YES; internal side=no, action=sell → +1 YES ✅

**Status**: ✅ Consistent (same canonical delta from both raw and normalized representation)

### 3. Exit Reduces Position
**Question**: Did the second fill reduce the absolute position?

**Expected**:
- Position before 56f13022: -1
- Position after 56f13022: 0
- `abs(0) < abs(-1)` ✅
- `sign(0 - (-1)) == -sign(-1)` → `sign(+1) == -sign(-1)` → `+1 == +1` ✅

**Status**: ✅ Mathematically valid exit, but cannot verify actual cache state

### 4. Exit Was Intended
**Question**: Was the second fill intended as an exit with parent position reference?

**Required evidence**:
- Intent kind for 56f13022: should be "EXIT"
- Parent position/lot: should reference fc400f76
- Exit reason: should be from exit policy (TP/SL/manual/etc.)

**Status**: ❌ Cannot verify without intent logs

### 5. Strategy Quality
**Question**: Why did the strategy enter NO and exit two minutes later? Was the gross edge sufficient to cover fees?

**Evidence**:
- Gross PnL: +0.16 USD
- Fees: 0.0175 USD
- Net PnL: +0.1425 USD ✅
- But we need strategy decision logs to understand why it chose NO and why it exited

**Status**: ⚠️ Financially positive on this pair, but strategy quality needs decision logs

---

## Missing Data Required for Conclusion

| Data | Source | Status |
|---|---|---|
| Position cache before/after each fill | `kalshi_fills.db` or PostgreSQL | ❌ Missing |
| Open lot state after entry | Position cache | ❌ Missing |
| Intent kind for both fills | Order intent logs | ❌ Missing |
| Client order ID mapping | Order intent logs | ❌ Missing |
| Exit reason for second fill | Order intent logs | ❌ Missing |
| Strategy source/agent ID | Decision logs | ❌ Missing |
| Realized PnL in cache | Position cache | ❌ Missing |
| Market close/settlement time | Market metadata | ❌ Missing |

---

## Classification

**BTC `KXBTC15M-26AUG081315-15` lifecycle**:
- ✅ Canonical exposure transitions are mathematically consistent
- ✅ Internal ledger deltas match raw exchange outcome_side
- ⚠️ Cannot verify actual cache position transitions
- ⚠️ Cannot verify intent kind or parent position reference
- ⚠️ Cannot verify exit was triggered by correct policy

**Status**: INSUFFICIENT_EVIDENCE to classify as POSITION_LIFECYCLE_VIOLATION

The sequence is **consistent with a valid NO entry→exit cycle**, not an additive exposure bug.

---

## Required Next Steps

1. **Access position cache** to verify `0 → -1 → 0` transition
2. **Access order intent logs** to verify exit was intentional with parent position reference
3. **Access strategy decision logs** to understand entry/exit rationale
4. **Verify realized PnL** in cache matches computed `+0.1425 USD`
5. **Check market metadata** to understand close time and why two-minute lifecycle occurred

**AUTONOMOUS ENTRIES REMAIN PAUSED** - Awaiting complete cache and intent evidence.