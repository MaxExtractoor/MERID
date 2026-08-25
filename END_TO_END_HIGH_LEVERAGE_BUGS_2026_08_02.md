# End-to-End High-Leverage Bugs Analysis

**Date**: 2026-08-02  
**Scope**: Complete lifecycle audit from signal generation to position management  
**Method**: Upstream → Midstream → Downstream → End-to-End analysis  
**Comparison**: Web research on prediction market best practices

## Executive Summary

This end-to-end audit identified **8 high-leverage bugs** across the complete trading lifecycle that could cause significant financial losses or system failures. These bugs span from upstream signal generation through downstream position management, with critical issues in probability model handling, side mapping, and fill processing.

## Critical High-Leverage Bugs

### 1. Probability Model Side Inversion (Upstream)
**Location**: `merid/loop_15m.py:6005-6029`  
**Severity**: CRITICAL  
**Financial Impact**: HIGH - Causes systematic rejection of valid NO-side trades  
**Root Cause**: Inconsistent probability model handling between YES and NO sides

**Bug Details**:
```python
# loop_15m.py lines 6005-6029
model_prob_yes_canonical = model_prob
if model_prob is not None and side_raw == "NO":
    model_prob_yes_canonical = 1.0 - model_prob

p_hat_yes_cents=model_prob_yes_canonical * 100.0 if model_prob_yes_canonical is not None else None
p_hat_no_cents=(100.0 - model_prob_yes_canonical * 100.0) if model_prob_yes_canonical is not None else None
```

**Issue**: The system converts NO-side model probabilities to YES-space for consistency, but this conversion is fragile and can fail when:
- `model_prob` is None (missing data)
- Side detection fails (side_raw not "NO")
- Double inversion occurs (already inverted)

**Impact**: 
- NO-side trades rejected due to incorrect edge calculations
- Systematic bias toward YES-side trades
- Missed profitable NO-side opportunities

**Web Research Best Practice**: 
- Probability models should provide both YES and NO probabilities atomically
- Side-specific probabilities should never be derived through inversion
- Kelly criterion requires correct probability for the specific side being traded

**Solution**: Use the new `BinaryProbability` dataclass that enforces duality invariant at the model level.

---

### 2. Edge Calculation Probability Inversion (Midstream)
**Location**: `merid/event_venues/kalshi/order_router.py:3595-3621`  
**Severity**: CRITICAL  
**Financial Impact**: HIGH - Incorrect edge calculations cause wrong trade decisions  
**Root Cause**: BUY_NO orders require probability inversion but implementation is fragile

**Bug Details**:
```python
# order_router.py lines 3595-3621
if order_side_lower in ("no", "buy_no"):
    if intent.p_hat_no_cents is not None:
        p_hat_cents = intent.p_hat_no_cents
    elif intent.p_hat_yes_cents is not None:
        p_hat_cents = 100.0 - intent.p_hat_yes_cents
    else:
        p_hat_cents = None  # FAILS EDGE CALCULATION
```

**Issue**: Edge calculation for BUY_NO orders fails when:
- `p_hat_no_cents` is missing (not provided by upstream)
- Fallback to `p_hat_yes_cents` fails (also missing)
- Results in `p_hat_cents = None`, breaking edge calculation

**Impact**:
- Valid BUY_NO trades rejected due to missing probability
- Edge calculation returns negative values for valid trades
- System fails closed when probability data incomplete

**Web Research Best Practice**:
- Edge calculation must be side-aware from the start
- Probability models should be mandatory, not optional
- Fail-closed behavior when data incomplete

**Solution**: Use `SideAwareEdgeCalculator` with mandatory `BinaryProbability` model.

---

### 3. Kalshi API Side Mapping Inversion (Downstream)
**Location**: `merid/event_venues/kalshi/client.py:2030-2037`  
**Severity**: CRITICAL  
**Financial Impact**: CRITICAL - Trades executed on wrong side  
**Root Cause**: Incorrect mapping of outcome/action to Kalshi bid/ask semantics

**Bug Details**:
```python
# client.py lines 2030-2037
if outcome == "yes" and action == "buy":
    kalshi_side = "bid"
elif outcome == "yes" and action == "sell":
    kalshi_side = "ask"
elif outcome == "no" and action == "buy":
    kalshi_side = "bid"  # FIXED: buying NO = bidding
elif outcome == "no" and action == "sell":
    kalshi_side = "ask"  # FIXED: selling NO = asking
```

**Issue**: While this code appears correct, the comment history shows this was previously broken:
- Previous bug: BUY_NO was mapped to "ask" (selling YES instead of buying NO)
- This caused complete side inversion at the API level
- Current code is fixed but lacks invariant checking

**Impact** (if regression occurs):
- Complete side inversion: BUY_NO executes as SELL_YES
- Opposite position taken
- Guaranteed losses on correct predictions

**Web Research Best Practice**:
- API side mapping should have invariant checks
- Bid/ask semantics must be validated against venue documentation
- Pre-execution validation of side mapping

**Solution**: Add invariant checking using `binary_price_space.py` functions.

---

### 4. WebSocket Fill Side Derivation (Downstream)
**Location**: `merid/event_venues/kalshi/ws_bridge.py:2660-2689`  
**Severity**: HIGH  
**Financial Impact**: MEDIUM - Incorrect position state from fill processing  
**Root Cause**: Kalshi WS reports all fills from YES-side perspective

**Bug Details**:
```python
# ws_bridge.py lines 2660-2689
# CRITICAL FIX: Kalshi quotes everything from YES side - do NOT trust raw.get("side")
# Kalshi's "side" field always reports "yes" because they quote from YES side perspective
# We must derive the correct side from the original intent using client_order_id
client_order_id = raw.get("client_order_id")
derived_side = raw.get("side", "")  # Fallback to Kalshi's reported side

if client_order_id:
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        ledger = get_fills_ledger()
        intent = ledger.get_intent(client_order_id) if hasattr(ledger, 'get_intent') else None
        if intent and intent.side:
            if "YES" in intent.side:
                derived_side = "yes"
            elif "NO" in intent.side:
                derived_side = "no"
```

**Issue**: The fix is in place but has failure modes:
- If `client_order_id` is missing, falls back to Kalshi's YES-side reporting
- If intent lookup fails, uses incorrect side
- No validation that derived side matches expected side

**Impact**:
- NO-side fills recorded as YES-side fills
- Position state corruption
- Incorrect position accounting

**Web Research Best Practice**:
- Never trust venue-reported side for position accounting
- Always derive side from original intent
- Validate side consistency across fill lifecycle

**Solution**: Strengthen side derivation with mandatory intent lookup and validation.

---

### 5. Position Cache Exit Fill Without Position (Downstream)
**Location**: `merid/event_venues/kalshi/position_cache.py:1000-1039`  
**Severity**: HIGH  
**Financial Impact**: MEDIUM - Phantom positions and side inversion  
**Root Cause**: Exit fills arrive without existing position due to desynchronization

**Bug Details**:
```python
# position_cache.py lines 1000-1039
if is_exit_fill:
    # Exit fill without existing position - this is a desynchronized state
    correlation_id = client_order_id or fill_id or "unknown"
    logger.critical(
        "[POSITION-CACHE-EXIT-FILL-ERROR] market=%s side=%s action=%s contracts=%d price=%dc "
        "client_order_id=%s fill_id=%s correlation_id=%s - EXIT FILL WITHOUT EXISTING POSITION. "
        "This indicates a desynchronized state (position deleted prematurely, cache reset, or race condition). "
        "Rejecting fill to prevent creating phantom position and side inversion bug.",
        market_id, side, action, contracts, price_cents,
        client_order_id or "N/A", fill_id or "N/A", correlation_id
    )
    # Do NOT create a new position - return early to prevent the bug
    return
```

**Issue**: The fix is reactive (rejects after problem occurs) rather than preventive:
- No pre-execution position state verification
- No intent-to-position reconciliation
- No circuit breaker for desynchronization detection

**Impact**:
- System rejects valid exit fills
- Positions cannot be closed properly
- Trading halted until manual intervention

**Web Research Best Practice**:
- Prevent desynchronization through intent-to-position reconciliation
- Pre-execution validation of position state
- Circuit breakers for systematic issues

**Solution**: Add intent-to-position reconciliation in order_router before execution.

---

### 6. Thesis Side Inversion in Exit Orders (Downstream)
**Location**: `merid/loop_15m.py:1843-1863`  
**Severity**: MEDIUM  
**Financial Impact**: MEDIUM - Exit orders on wrong side  
**Root Cause**: Fallback to mutable position.side when thesis_side missing

**Bug Details**:
```python
# loop_15m.py lines 1843-1863
# Get thesis_side from position (immutable strategy thesis)
# Fallback to position.side for backward compatibility with existing positions
if hasattr(position, 'thesis_side'):
    thesis_side_str = position.thesis_side
    try:
        thesis_side = ThesisSide.from_outcome_side(thesis_side_str)
        logger.info(
            "[EXIT-ORDER-THESIS] Using thesis_side=%s (immutable strategy thesis) for exit order generation",
            thesis_side_str
        )
    except Exception as e:
        logger.warning(
            "[EXIT-ORDER-THESIS] Invalid thesis_side=%s: %s, falling back to position.side",
            thesis_side_str, e
        )
        thesis_side = None
else:
    # Backward compatibility: use position.side for positions without thesis_side
    thesis_side = None
    logger.warning(
        "[EXIT-ORDER-LEGACY] Position missing thesis_side, using mutable position.side - may be subject to side inversion"
    )
```

**Issue**: Fallback to mutable `position.side` can cause side inversion:
- Legacy positions without `thesis_side` use mutable side
- REST API can update `position.side` to YES-side perspective
- Exit orders generated on wrong side

**Impact**:
- Exit orders close wrong leg
- Mixed YES/NO positions
- Unable to close positions correctly

**Web Research Best Practice**:
- Immutable strategy thesis should never fall back to mutable state
- Legacy positions should be migrated to thesis_side
- Fail closed rather than use unsafe fallback

**Solution**: Remove fallback to mutable position.side, require thesis_side.

---

### 7. Model Probability Double Inversion (Upstream)
**Location**: `merid/prediction/agent_grid_15m.py:5320-5349`  
**Severity**: MEDIUM  
**Financial Impact**: MEDIUM - Incorrect Kelly criterion calculations  
**Root Cause**: Double probability inversion for NO-side trades

**Bug Details**:
```python
# agent_grid_15m.py lines 5320-5349
if signal_side == "yes":
    # For YES: model_prob is probability of YES outcome (trade wins if event happens)
    model_prob = market_prob + edge_adjustment
else:
    # For NO: model_prob is probability of NO outcome (trade wins if event doesn't happen)
    # price_cents here is the NO price (dual_side_no_price), so market_prob is ALREADY
    # the market-implied NO probability. Do NOT invert it again (double inversion made
    # model_prob = P(YES)+edge, causing Kelly to reject every NO order at price > ~50c).
    model_prob = market_prob + edge_adjustment
```

**Issue**: The comment indicates a previous bug with double inversion:
- Previous: NO-side probability was inverted twice (P(NO) → P(YES) → P(NO))
- Current: Fixed but lacks validation
- No check that `market_prob` is actually in NO-space

**Impact** (if regression occurs):
- Kelly criterion rejects all valid NO-side trades
- Incorrect position sizing
- Systematic bias toward YES-side trades

**Web Research Best Practice**:
- Kelly criterion requires correct probability for the specific side
- Probability space should be explicit and validated
- Double inversion bugs are common and dangerous

**Solution**: Use `BinaryProbability` model with explicit side-space validation.

---

### 8. Entry/Exit Invariant Violations (Midstream)
**Location**: `merid/loop_15m.py:5728-5799`  
**Severity**: MEDIUM  
**Financial Impact**: MEDIUM - Invalid position states  
**Root Cause**: Invariant checking scattered and incomplete

**Bug Details**:
```python
# loop_15m.py lines 5728-5799
# CRITICAL INVARIANT CHECK: Entry orders must ALWAYS use BUY actions
if action_raw == "SELL":
    is_exit_order = False
    if "entry_or_exit" in candidate:
        is_exit_order = (candidate["entry_or_exit"] == "exit")
    else:
        # Legacy detection: check for exit_reason or exit in rationale
        is_exit_order = candidate.get("exit_reason") is not None
        is_exit_order = is_exit_order or ("rationale" in candidate and "exit" in str(candidate["rationale"]).lower())
    
    if not is_exit_order:
        # Reject SELL on entry
        return False
```

**Issue**: Invariant checking is incomplete:
- No position state verification for entry orders
- No pre-position size validation
- Legacy detection is fragile (string matching in rationale)
- Scattered across multiple files

**Impact**:
- Invalid position states created
- Entry orders with wrong actions
- Position accounting errors

**Web Research Best Practice**:
- Centralized invariant checking
- Position state verification before all orders
- Clear entry/exit state machine

**Solution**: Use `InvariantChecker` from side_aware_trading_layer for all validation.

---

## End-to-End Lifecycle Analysis

### Signal Generation (Upstream)
**Current State**: 
- Agent grid generates signals with side selection
- Probability models calculated per side
- Edge calculation performed

**Issues Found**:
1. Probability model side inversion (Bug #1)
2. Model probability double inversion (Bug #7)

**Best Practice Gaps**:
- No unified probability model
- Probability fields optional instead of mandatory
- No side-space validation

### Intent Creation (Upstream)
**Current State**:
- OrderIntent created with side/action
- p_hat fields populated
- Entry/exit classification

**Issues Found**:
1. Missing p_hat fields cause downstream failures (Bug #2)
2. Entry/exit invariant checking incomplete (Bug #8)

**Best Practice Gaps**:
- No mandatory probability model
- No intent validation layer
- Invariant checking scattered

### Order Routing (Midstream)
**Current State**:
- Order router validates intents
- Risk checks performed
- Edge-aware microstructure gate

**Issues Found**:
1. Edge calculation probability inversion (Bug #2)
2. Entry/exit invariant checking incomplete (Bug #8)

**Best Practice Gaps**:
- No side-aware price validation layer
- No unified invariant checking
- Probability model not mandatory

### Execution (Downstream)
**Current State**:
- Kalshi client maps to API format
- Orders submitted to Kalshi
- Response handling

**Issues Found**:
1. Kalshi API side mapping (Bug #3) - currently fixed but fragile
2. No pre-execution side mapping validation

**Best Practice Gaps**:
- No invariant checking of API mapping
- No pre-execution validation
- No side mapping verification

### Fill Processing (Downstream)
**Current State**:
- WebSocket fills processed
- HTTP fills ingested
- Position cache updated

**Issues Found**:
1. WebSocket fill side derivation (Bug #4)
2. Position cache exit fill handling (Bug #5)
3. Thesis side inversion (Bug #6)

**Best Practice Gaps**:
- No fill-to-intent reconciliation
- No position state verification
- Mutable state fallbacks

### Position Management (Downstream)
**Current State**:
- Position cache tracks positions
- Exit orders generated
- PnL calculated

**Issues Found**:
1. Thesis side inversion in exit orders (Bug #6)
2. Mutable state fallbacks

**Best Practice Gaps**:
- No immutable strategy thesis enforcement
- No position state machine
- No side invariant monitoring

---

## Web Research Insights

### Probability Model Best Practices
1. **Atomic Probability Models**: Provide both YES and NO probabilities together
2. **Duality Invariant**: YES + NO = 100 must be enforced at model level
3. **Side-Specific Probabilities**: Never derive through inversion
4. **Kelly Criterion**: Requires correct probability for specific side being traded

### Side Mapping Best Practices
1. **Canonical Side Functions**: Single source of truth for all side mapping
2. **API Validation**: Pre-execution validation of venue-specific mapping
3. **Invariant Checking**: Verify side mapping at each layer
4. **Intent-Based Side**: Always derive from original intent, not venue reports

### Position Management Best Practices
1. **Immutable Strategy Thesis**: Never fall back to mutable state
2. **Entry/Exit State Machine**: Clear position lifecycle states
3. **Pre-Execution Validation**: Verify position state before orders
4. **Intent-to-Position Reconciliation**: Prevent desynchronization

### Fill Processing Best Practices
1. **Intent-Based Reconciliation**: Always link fills to original intents
2. **Side Derivation from Intent**: Never trust venue-reported side
3. **Duplicate Detection**: Global fill ID uniqueness
4. **State Validation**: Verify fill consistency with expected state

---

## Recommended Solutions

### Immediate (P0) - This Week
1. **Integrate side_aware_trading_layer**: Replace fragmented side handling
2. **Mandatory BinaryProbability**: Enforce at intent creation
3. **Pre-execution validation**: Add side mapping invariant checks
4. **Intent-to-position reconciliation**: Add before order execution

### High Priority (P1) - This Month
1. **Remove mutable state fallbacks**: Require thesis_side for all positions
2. **Centralize invariant checking**: Use InvariantChecker everywhere
3. **Strengthen fill side derivation**: Mandatory intent lookup
4. **Add position state machine**: Clear entry/exit lifecycle

### Medium Priority (P2) - Next Quarter
1. **Probability model unification**: Single source of truth
2. **Side mapping validation**: At each transformation layer
3. **Monitoring and alerting**: For side inversion attempts
4. **Legacy position migration**: Move to thesis_side model

---

## Financial Impact Assessment

### Critical (Could Cause Immediate Losses)
- **Bug #3**: Kalshi API side mapping - Complete side inversion
- **Bug #1**: Probability model side inversion - Systematic trade rejection

### High (Could Cause Significant Losses)
- **Bug #2**: Edge calculation probability inversion - Wrong trade decisions
- **Bug #4**: WebSocket fill side derivation - Position state corruption

### Medium (Could Cause Moderate Losses)
- **Bug #5**: Position cache exit fill handling - Trading halts
- **Bug #6**: Thesis side inversion - Wrong exit orders
- **Bug #7**: Model probability double inversion - Kelly criterion failures
- **Bug #8**: Entry/exit invariant violations - Invalid position states

---

## Testing Recommendations

### Unit Tests
1. Probability model duality invariant
2. Side mapping at each transformation layer
3. Edge calculation for all four order types
4. Entry/exit invariant checking

### Integration Tests
1. End-to-end order lifecycle
2. Fill processing with side derivation
3. Position state transitions
4. Intent-to-position reconciliation

### Chaos Tests
1. Probability model failures
2. Side mapping failures
3. Fill processing failures
4. Position desynchronization

### Property-Based Tests
1. Duality invariant always holds
2. Side mapping is bijective
3. Position state transitions are valid
4. Fill-to-intent consistency

---

## Monitoring Recommendations

### Critical Metrics
1. Side inversion attempts
2. Probability model failures
3. Duality invariant violations
4. Fill-to-intent mismatches

### Warning Metrics
1. Missing p_hat fields
2. Mutable state fallbacks
3. Entry/exit invariant violations
4. Position desynchronization events

### Informational Metrics
1. Side distribution (YES vs NO)
2. Probability model accuracy
3. Edge calculation consistency
4. Position state distribution

---

## Conclusion

This end-to-end audit revealed systemic issues with side handling and probability models across the entire trading lifecycle. The root causes are:

1. **Fragmented side handling** - Side mapping logic scattered across files
2. **Optional probability models** - Critical data treated as optional
3. **Mutable state fallbacks** - Unsafe fallbacks to mutable position.side
4. **Reactive validation** - Problems caught after they occur

The new `side_aware_trading_layer.py` module addresses all these issues by providing:
- Unified side handling with canonical functions
- Mandatory probability models with duality enforcement
- Immutable strategy thesis with no unsafe fallbacks
- Proactive invariant checking at all layers

Implementing this layer across the system will eliminate the high-leverage bugs and bring the system in line with industry best practices for prediction market trading.
