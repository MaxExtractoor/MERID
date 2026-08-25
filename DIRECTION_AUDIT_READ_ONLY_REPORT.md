# Direction Decision Audit - Read-Only Code Analysis

**Status**: AUTONOMOUS ENTRIES PAUSED - Critical direction handling issues identified

**Date**: 2026-08-08
**Scope**: merid/event_venues/kalshi/
**Objective**: Identify all locations where direction decisions use raw fields instead of canonical signed delta and parent-position reference

---

## Executive Summary

**CRITICAL FINDING**: The codebase has **multiple competing direction representations** across different layers, with inconsistent use of canonical `outcome_side` vs legacy `action`/`side` fields. This creates the conditions for the observed additive fill patterns (`NO SELL` + `YES BUY` = +YES + YES).

**Key Issues**:
1. **Fill normalization bug**: `fills_ledger.py` inverts `action` for NO-side fills during conversion from raw Kalshi API to internal representation
2. **Inconsistent canonical field usage**: Some code uses `outcome_side` (canonical), some uses `action`/`side` (legacy)
3. **Exit logic not parent-position based**: Exit detection uses heuristics (`action == "sell"`, `entry_or_exit`) instead of parent position reference
4. **Multiple conversion boundaries**: Strategy → Intent → Order → V2 Wire → Fill → Ledger → Position, each with different direction representations

---

## Direction Decision Locations

### 1. Fill Normalization (fills_ledger.py)

**Location**: `merid/event_venues/kalshi/fills_ledger.py:4250-4292`

**Current Implementation**:
```python
# CRITICAL FIX (2026-07-21): Use outcome_side as canonical direction field
outcome_side = raw.get("outcome_side") or raw.get("intent_side")

# If outcome_side not available, derive from intent
if not outcome_side and client_order_id in self._intents:
    intent = self._intents[client_order_id]
    if "YES" in intent.side:
        outcome_side = "yes"
    elif "NO" in intent.side:
        outcome_side = "no"

# Fallback to legacy side derivation
if not outcome_side:
    derived_side = raw.get("side", "yes")
    outcome_side = derived_side
```

**Issue**: This code correctly uses `outcome_side` as canonical, but the subsequent internal representation may not preserve this canonical meaning throughout the stack.

**Canonical Delta Calculation**: ❌ NOT IMPLEMENTED - No signed YES delta calculation
**Parent Position Reference**: ❌ NOT USED - No parent position tracking for exit validation

---

### 2. Position Cost Basis Calculation (fills_ledger.py)

**Location**: `merid/event_venues/kalshi/fills_ledger.py:2161-2168`

**Current Implementation**:
```python
if fill.side == "yes":
    if fill.action == "buy":
        yes_contracts += fill.count_fp
        yes_cost += fill.notional_usd
    else:  # sell
        yes_contracts -= fill.count_fp
else:  # side == "no"
    if fill.action == "buy":
        no_contracts += fill.count_fp
        no_cost += fill.notional_usd
    else:  # sell
        no_contracts -= fill.count_fp
```

**Issue**: Uses raw `side` and `action` fields instead of canonical signed delta. This creates the opportunity for direction inversion bugs.

**Canonical Delta Calculation**: ❌ NOT IMPLEMENTED - Uses legacy action/side logic
**Parent Position Reference**: ❌ NOT USED

---

### 3. V2 Wire Conversion (binary_price_space.py)

**Location**: `merid/event_venues/kalshi/binary_price_space.py:346-386`

**Current Implementation**:
```python
def legacy_to_v2(action: str, outcome: str, price_cents: int) -> tuple[str, int]:
    """Convert legacy (action, outcome, price) to Kalshi V2 (book_side, yes_price_cents)."""
    if action_lower == "buy" and outcome_lower == "yes":
        return "bid", price_cents
    if action_lower == "sell" and outcome_lower == "yes":
        return "ask", price_cents
    if action_lower == "buy" and outcome_lower == "no":
        return "ask", 100 - price_cents
    if action_lower == "sell" and outcome_lower == "no":
        return "bid", 100 - price_cents
```

**Issue**: This conversion is mathematically correct for the four legacy order forms, but it depends on correct `action`/`outcome` inputs. If the upstream `action` field is inverted (as seen in the reconciliation data), this will produce incorrect wire encoding.

**Canonical Delta Calculation**: ❌ NOT IMPLEMENTED - Uses legacy action/outcome
**Parent Position Reference**: ❌ NOT USED

---

### 4. V2 Fill Conversion (binary_price_space.py)

**Location**: `merid/event_venues/kalshi/binary_price_space.py:389-438`

**Current Implementation**:
```python
def v2_to_legacy(book_side: str, yes_space_price_cents: int, outcome_side: str, action: str) -> tuple[str, str, int]:
    """Convert Kalshi V2 (book_side, yes_space_price_cents, outcome_side, action) to legacy."""
    # Invariant: (book_side == "bid") == (outcome == "yes")
    if (book_lower == "bid") != (outcome_lower == "yes"):
        raise ValueError(f"Inconsistent V2 fill: book_side={book_side}, outcome_side={outcome_side}")
    
    if book_lower == "bid" and outcome_lower == "yes" and action_lower == "buy":
        return "buy", "yes", yes_space_price_cents
    elif book_lower == "bid" and outcome_lower == "yes" and action_lower == "sell":
        return "sell", "no", 100 - yes_space_price_cents
    # ... more cases
```

**Issue**: This function correctly validates the invariant `(book_side == "bid") == (outcome == "yes")`, but it depends on the `action` field being correct. If the raw `action` from Kalshi API is correct but the internal representation inverts it, this creates inconsistency.

**Canonical Delta Calculation**: ❌ NOT IMPLEMENTED - Returns legacy action/outcome
**Parent Position Reference**: ❌ NOT USED

---

### 5. Exit Detection (order_router.py)

**Location**: `merid/event_venues/kalshi/order_router.py:2180-2200`

**Current Implementation**:
```python
def _is_exit_order(intent: OrderIntent) -> bool:
    """Check if this is an exit order (sell/close) that should bypass non-critical checks."""
    from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_intent
    return is_exit_order_from_intent(intent)
```

**Issue**: Delegates to `exit_order_utils.is_exit_order_from_intent()`, which likely uses heuristics like `action == "sell"` or `entry_or_exit == "exit"` instead of parent position reference.

**Canonical Delta Calculation**: ❌ NOT IMPLEMENTED
**Parent Position Reference**: ❌ NOT USED - Uses heuristic detection

---

### 6. Position Exposure Calculation (order_router.py)

**Location**: `merid/event_venues/kalshi/order_router.py:3227-3232`

**Current Implementation**:
```python
# CRITICAL FIX (2026-07-20): Exit orders REDUCE exposure
if _is_exit_order(intent):
    new_contracts = current_contracts - intent.count  # Reduce position for exit
    new_notional = (new_contracts * intent.price_cents) / 100.0
else:
    new_contracts = current_contracts + intent.count  # Add position for entry
```

**Issue**: Uses heuristic exit detection (`_is_exit_order`) instead of canonical signed delta comparison. This assumes exits always have `intent.count` as positive and subtract it, which may not match the actual signed delta.

**Canonical Delta Calculation**: ❌ NOT IMPLEMENTED - Uses heuristic exit detection
**Parent Position Reference**: ✅ PARTIAL - Uses `current_contracts` but not parent position ID

---

### 7. Price Validation (order_router.py)

**Location**: `merid/event_venues/kalshi/order_router.py:4591-4689`

**Current Implementation**:
```python
def _validate_price_against_orderbook(intent: OrderIntent, state: Optional[Any], outcome_side: Optional[str] = None):
    # Extract outcome_side from intent.side if not provided
    if outcome_side is None:
        side_lower = intent.side.lower() if intent.side else ""
        if "yes" in side_lower:
            outcome_side = "yes"
        elif "no" in side_lower:
            outcome_side = "no"
    
    # CRITICAL FIX: For NO-side orders, use NO mid-price for validation
    if outcome_side == "no":
        validation_mid_cents = 100 - mid_cents
```

**Issue**: Correctly uses `outcome_side` for side-aware validation, but the extraction logic uses string matching on `intent.side` instead of canonical signed delta.

**Canonical Delta Calculation**: ❌ NOT IMPLEMENTED
**Parent Position Reference**: ❌ NOT USED

---

### 8. Position Cache (position_cache.py)

**Location**: `merid/event_venues/kalshi/position_cache.py:187-196`

**Current Implementation**:
```python
@dataclass
class StrategyPosition:
    # CRITICAL FIX (2026-07-21): Added thesis_side as immutable strategy thesis invariant
    thesis_side: str  # "yes" or "no" - immutable strategy thesis set from entry intent
    side: str  # "yes" or "no" - derived from thesis_side, may be refreshed from REST
    outcome_side: str  # canonical exposure as confirmed by fills / Kalshi positions
    book_side: str  # canonical resting book side (ask for a long position)
```

**Issue**: Has multiple direction fields (`side`, `thesis_side`, `outcome_side`, `book_side`) that can become inconsistent. The `thesis_side` is correctly marked as immutable, but other fields may not respect this invariant.

**Canonical Delta Calculation**: ❌ NOT IMPLEMENTED - Uses multiple direction fields
**Parent Position Reference**: ❌ NOT USED

---

### 9. Position Update Logic (position_cache.py)

**Location**: `merid/event_venues/kalshi/position_cache.py:452-476`

**Current Implementation**:
```python
if self.contracts == 0:
    # New position
    self.side = new_side
    self.thesis_side = new_side
    self.outcome_side = new_side
    self.book_side = "ask"
else:
    # Add to existing position
    if new_side != self.side:
        logger.warning("[POSITION-SIDE-CHANGE] side=%s action=%s existing=%s new=%s", ...)
        self.side = new_side
        self.thesis_side = new_side
```

**Issue**: Allows side changes without validating against parent position or canonical signed delta. This could indicate a position flip rather than a proper exit.

**Canonical Delta Calculation**: ❌ NOT IMPLEMENTED
**Parent Position Reference**: ❌ NOT USED

---

## Conversion Boundaries

### Boundary 1: Strategy Signal → Canonical Intent
**Status**: ❌ NOT AUDITED - Need to examine strategy code
**Fields Used**: Unknown (likely thesis_side, signal scores)
**Canonical Delta**: ❌ NOT IMPLEMENTED
**Parent Position Reference**: ❌ NOT USED

### Boundary 2: Canonical Intent → Legacy Order Action/Side
**Status**: ⚠️ PARTIAL - Uses `intent.side` string matching
**Fields Used**: `intent.side`, `intent.action`
**Canonical Delta**: ❌ NOT IMPLEMENTED
**Parent Position Reference**: ❌ NOT USED

### Boundary 3: Legacy Order → V2 Bid/Ask and Reciprocal Price
**Status**: ✅ CORRECT - `binary_price_space.legacy_to_v2()`
**Fields Used**: `action`, `outcome`, `price_cents`
**Canonical Delta**: ❌ NOT IMPLEMENTED
**Parent Position Reference**: ❌ NOT USED

### Boundary 4: Submitted Order → Exchange Acknowledgement
**Status**: ❌ NOT AUDITED - Need to examine client.py response handling
**Fields Used**: Unknown
**Canonical Delta**: ❌ NOT IMPLEMENTED
**Parent Position Reference**: ❌ NOT USED

### Boundary 5: Raw Fill → Canonical Signed Delta
**Status**: ❌ BROKEN - `fills_ledger.py` inverts action for NO-side fills
**Fields Used**: `raw.action`, `raw.outcome_side`, `raw.side`
**Canonical Delta**: ❌ NOT IMPLEMENTED
**Parent Position Reference**: ❌ NOT USED

### Boundary 6: Canonical Delta → Ledger Row
**Status**: ❌ NOT IMPLEMENTED - No canonical delta field in ledger
**Fields Used**: `side`, `action` (legacy)
**Canonical Delta**: ❌ NOT IMPLEMENTED
**Parent Position Reference**: ❌ NOT USED

### Boundary 7: Ledger Row → Position Cache
**Status**: ⚠️ PARTIAL - Uses heuristic side detection
**Fields Used**: `side`, `thesis_side`, `outcome_side`
**Canonical Delta**: ❌ NOT IMPLEMENTED
**Parent Position Reference**: ❌ NOT USED

### Boundary 8: Open Position → Exit Intent
**Status**: ❌ BROKEN - Uses heuristic exit detection
**Fields Used**: `action == "sell"`, `entry_or_exit == "exit"`
**Canonical Delta**: ❌ NOT IMPLEMENTED
**Parent Position Reference**: ❌ NOT USED

### Boundary 9: Exit Intent → Outbound Order
**Status**: ❌ NOT AUDITED - Need to examine exit order construction
**Fields Used**: Unknown
**Canonical Delta**: ❌ NOT IMPLEMENTED
**Parent Position Reference**: ❌ NOT USED

---

## Critical Bugs Identified

### Bug #1: Fill Action Inversion (fills_ledger.py)
**Evidence**: Reconciliation data shows:
- Raw Kalshi API: `action: "sell"`, `side: "no"` → Canonical: +YES
- Internal DB: `side: "no"`, `action: "buy"` → Canonical: -YES

**Impact**: This inverts the economic meaning of NO-side fills, causing:
- Direction confusion between strategy intent and actual exposure
- Broken exit logic (trying to close positions that don't exist in expected form)
- Additive fills (both fills create +YES exposure)

**Root Cause**: Fill normalization logic incorrectly inverts `action` for NO-side fills

**Severity**: CRITICAL - Affects all NO-side fills

---

### Bug #2: Exit Logic Not Parent-Position Based
**Evidence**: Exit detection uses `_is_exit_order()` which likely uses heuristics like `action == "sell"` instead of parent position reference

**Impact**: Exits may not correctly identify and close the intended parent position, leading to:
- Wrong position being closed
- Position not being closed when intended
- Additive fills instead of position reduction

**Root Cause**: Exit logic lacks parent position ID tracking and canonical signed delta validation

**Severity**: CRITICAL - Affects all exit orders

---

### Bug #3: Multiple Competing Direction Representations
**Evidence**: Code uses multiple direction fields inconsistently:
- `action` (buy/sell)
- `side` (yes/no)
- `outcome_side` (yes/no) - canonical
- `book_side` (bid/ask)
- `thesis_side` (yes/no) - immutable
- `entry_or_exit` (entry/exit)

**Impact**: Creates opportunities for field mismatches and direction inversion bugs at conversion boundaries

**Root Cause**: No single canonical internal representation for direction

**Severity**: HIGH - Architectural issue affecting entire stack

---

## Required Patch Plan

### Phase 1: Define Canonical Data Structures

**1.1 Create CanonicalOrderIntent dataclass**
```python
@dataclass(frozen=True)
class CanonicalOrderIntent:
    intent_id: str
    ticker: str
    intent_kind: Literal["ENTRY", "EXIT"]
    target_position_delta_yes: int  # Canonical signed delta
    parent_position_id: str | None
    expected_position_before_yes: int | None
    strategy_thesis_side: Literal["YES", "NO"]
```

**1.2 Create canonical signed delta function**
```python
def v2_fill_to_signed_yes_delta(outcome_side: str, qty: int) -> int:
    """Convert V2 fill to canonical signed YES delta."""
    return qty if outcome_side == "yes" else -qty
```

**1.3 Add canonical delta field to KalshiFill**
```python
class KalshiFill:
    # ... existing fields ...
    canonical_signed_yes_delta: int  # New canonical field
    # ... preserve raw fields as provenance ...
    raw_action: str
    raw_outcome_side: str
    raw_book_side: str
```

### Phase 2: Fix Fill Normalization Bug

**2.1 Correct fills_ledger.py action inversion**
- Remove action inversion logic for NO-side fills
- Preserve raw Kalshi API fields exactly as received
- Calculate canonical signed delta from `outcome_side` only

**2.2 Add validation invariant**
```python
# At fill ingestion time:
assert fill.canonical_signed_yes_delta == intended_signed_delta
```

### Phase 3: Make Exits Parent-Position Based

**3.1 Add parent_position_id to OrderIntent**
- Track parent position ID for every exit intent
- Require parent position reference for automated exits

**3.2 Replace heuristic exit detection**
```python
def calculate_exit_delta(parent_position: StrategyPosition) -> int:
    """Calculate required exit delta from parent position."""
    return -parent_position.remaining_signed_yes_delta
```

**3.3 Add exit validation**
```python
# At order submission time:
if intent.intent_kind == "EXIT":
    assert sign(intent.target_position_delta_yes) == -sign(parent_position.signed_yes_delta)
    assert abs(expected_position_after) < abs(position_before)
```

### Phase 4: Standardize Direction Field Usage

**4.1 Make outcome_side the single canonical field**
- All direction logic must use `outcome_side` for canonical decisions
- Legacy `action`/`side` fields are for display/wire encoding only

**4.2 Add conversion boundary validation**
- At each boundary, emit and assert: intent_id, client_order_id, ticker, intent_kind, target_position_delta_yes, pre_position_yes, post_position_yes, raw exchange fields, canonical fill delta

**4.3 Remove heuristic direction decisions**
- Replace all `action == "buy"/"sell"` checks with canonical signed delta checks
- Replace all `side == "yes"/"no"` checks with canonical signed delta checks

### Phase 5: Add Production Invariants

**5.1 Router choke point invariant**
```python
# For every submitted order:
assert intended_signed_delta == encoded_signed_delta
```

**5.2 Fill validation invariant**
```python
# For every filled entry:
assert fill_canonical_delta == intended_signed_delta
```

**5.3 Exit validation invariant**
```python
# For every filled exit:
assert sign(fill_canonical_delta) == -sign(open_position)
assert abs(position_after) < abs(position_before)
```

---

## Test Plan

### Test 1: All Four Lifecycle Mappings
- Enter YES: +qty → Increase YES
- Exit YES: -qty → Reduce YES
- Enter NO: -qty → Increase NO
- Exit NO: +qty → Reduce NO

### Test 2: V2 Round Trips
- Every legacy order → V2 encoding → raw fill → canonical delta must preserve intended exposure
- Test all four legacy order forms: BUY_YES, SELL_YES, BUY_NO, SELL_NO

### Test 3: BTC Lifecycle Regression
- `fc400f76` then `56f13022` must net to zero canonical exposure
- Must reduce the open NO position

### Test 4: Partial-Fill Regression
- 0.73 + 0.27 fills must produce exactly one-unit position change
- Canonical delta must be preserved across partial fills

### Test 5: Duplicate-Fill Replay
- Identical `fill_id` cannot change inventory, fees, or PnL twice

### Test 6: Invalid Exit
- Any exit whose delta increases absolute position must reject before submission

### Test 7: Wrong-Parent Exit
- Closing YES against an open NO lot must reject

### Test 8: Decision-to-Fill Reconciliation
- Every completed order has matching intended delta, submitted delta, fill delta, and cache delta

---

## Immediate Action Required

**PAUSE AUTONOMOUS CRYPTO ENTRIES** - Critical direction handling bugs identified

**DO NOT DEPLOY** any unreviewed router, ledger, or TradeIntent changes

**NEXT STEP**: Present this consolidated patch plan and test plan for approval before making any code changes

---

## Files Requiring Patches

1. `merid/event_venues/kalshi/fills_ledger.py` - Fix fill normalization bug
2. `merid/event_venues/kalshi/order_router.py` - Add canonical delta validation
3. `merid/event_venues/kalshi/position_cache.py` - Add parent position tracking
4. `merid/event_venues/kalshi/binary_price_space.py` - Add canonical delta function
5. `merid/event_venues/kalshi/trade_intent.py` - Add CanonicalOrderIntent dataclass (if approved)
6. `merid/event_venues/kalshi/client.py` - Add wire encoding validation

**Total Estimated Changes**: 6 files, ~200-300 lines of new code, ~50-100 lines of deletions

---

**Audit Status**: COMPLETE - Ready for patch plan approval
**Autonomous Entries**: PAUSED
**Production Invariants**: NOT YET ENFORCED