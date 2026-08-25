# Parity and Counter Bug Fix Summary

**Date**: 2026-08-02  
**Issue**: Systemic threshold/triage bug causing false parity vetoes and counter mismatches

## Root Cause Analysis

The logs showed a systemic issue where:
1. **Parity Block**: `PARITY BLOCKED` messages showed `edge_yes=-0.0150` and `edge_no=0.0150` at exactly `min_edge=0.0150`, indicating a boundary-condition bug
2. **Counter Mismatch**: `COUNTER-SANITY-WARNING` showed `1 candidate != 0 executed + 2 rejections`, indicating double-counting in rejection counters
3. **Signal Quality**: Strong BTC/ETH signals (15% and 3.8% edges) were being rejected, confirming the issue was downstream in gating, not signal generation

## Fixes Implemented

### 1. Fixed Threshold Comparison Bug in `select_winner_side`

**File**: `merid/prediction/canonical_edge.py`

**Problem**: Used `>= min_edge` comparison which failed at exact boundary conditions due to floating-point precision.

**Solution**: Changed to epsilon-based comparison: `>= min_edge - epsilon`

```python
# Before:
if edge_yes > edge_no + epsilon and edge_yes >= min_edge:
    return "yes"

# After:
if edge_yes > edge_no + epsilon and edge_yes >= min_edge - epsilon:
    return "yes"
```

**Impact**: Prevents false rejections when edge is exactly at threshold (e.g., 0.0150).

### 2. Fixed Double-Counting in Rejection Counters

**File**: `merid/loop_15m.py`

**Problem**: `parity_blocked` counter was incremented in 3 places:
- Line 6294: When `chosen_side == "none"`
- Line 6372: When `is_winner_mismatch`
- Line 6392: Final decision point

This caused the counter to be incremented 2-3 times per rejection.

**Solution**: Removed counter increments from intermediate checkpoints, keeping only the final increment at the decision point (line 6392).

**Added detailed rejection categories**:
- `parity_edge_threshold`: Edge threshold failures
- `parity_winner_mismatch`: Winner mismatch failures
- `parity_price_violation`: Price parity violations

**Impact**: Eliminates counter sanity mismatch warnings.

### 3. Added Candidate Lifecycle Tracking

**Files**: 
- `merid/prediction/agent_grid_15m.py` (candidate generation)
- `merid/loop_15m.py` (lifecycle events)

**Problem**: No single source of truth for candidate state transitions, making invariant checking impossible.

**Solution**: 
- Added unique `candidate_id` to each candidate (UUID-based)
- Added lifecycle state machine: `GENERATED` → `RECEIVED` → `EXECUTED`/`REJECTED`/`BLOCKED_*`
- Added event log for all state transitions with timestamps and context
- Added lifecycle sanity check comparing event log against counters

**States**:
- `GENERATED`: Candidate created by agent
- `RECEIVED`: Candidate received by loop_15m
- `EXECUTED`: Order submitted successfully
- `REJECTED`: Order submission failed
- `BLOCKED_PARITY`: Parity validation failed
- `BLOCKED_EDGE_THRESHOLD`: Edge below threshold
- `BLOCKED_DUPLICATE`: Duplicate order in window
- `BLOCKED_POSITION`: Position already exists
- `BLOCKED_RESTING_ORDER`: Resting order exists

**Impact**: Provides single source of truth for candidate flow, enables invariant checking: `candidates = executed + rejected + blocked + expired`.

### 4. Separated Parity Check from Edge Threshold Check

**File**: `merid/loop_15m.py`

**Problem**: Parity validation and edge threshold were conflated, making it unclear which gate was blocking candidates.

**Solution**: 
- Added `edge_threshold_passed` flag to track edge threshold separately
- Only run parity validation if edge threshold passes
- Edge threshold failures are now logged as `BLOCKED_EDGE_THRESHOLD`, not `BLOCKED_PARITY`
- Clear precedence: Edge threshold first, then parity validation

**Precedence**:
1. Edge threshold: "Is the opportunity strong enough?"
2. Parity validation: "Is the market directionally symmetric / disallowed?"

**Impact**: Clear separation of concerns, better debugging, eliminates false parity vetoes.

### 5. Added Unit Tests for Boundary Cases

**File**: `tests/test_canonical_edge_boundary_cases.py`

**Problem**: No tests for boundary conditions that caused the original bug.

**Solution**: Added comprehensive test suite covering:
- Edge exactly at min_edge
- Edge one epsilon above/below min_edge
- Negative edge at -min_edge
- Both edges negative
- Both edges below threshold
- Edges within epsilon (tie)
- Clear YES/NO wins
- Original bug case (edge_yes=-0.0150, edge_no=0.0150)
- Floating point precision

**Results**: All 11 tests pass.

**Impact**: Prevents regression of boundary-condition bugs.

## Verification

### Counter Sanity Check
The lifecycle event log now provides a second source of truth for verification:
```python
lifecycle_terminal_count = sum(1 for e in event_log if e.to_state in terminal_states)
if total_candidates != lifecycle_terminal_count:
    logger.warning("[LIFECYCLE-SANITY-WARNING] ...")
```

### Original Bug Case
The original bug case from logs (`edge_yes=-0.0150, edge_no=0.0150`) now correctly returns "no" instead of "none", allowing the trade to execute.

## Summary

The fix addresses the systemic threshold/triage bug by:
1. ✅ Normalizing edge semantics with epsilon-based comparison
2. ✅ Making parity a clearly separated risk gate with clear precedence
3. ✅ Reconciling candidate/execution/rejection state with a single source of truth (event log)
4. ✅ Eliminating double-counting in rejection counters
5. ✅ Adding comprehensive unit tests for boundary cases

The strong BTC/ETH signals should now execute correctly without false parity vetoes, and the counter sanity warnings should be eliminated.
