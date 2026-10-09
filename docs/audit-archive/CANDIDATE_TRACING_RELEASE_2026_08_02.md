# Candidate Tracing & Lifecycle Reconciliation Release
**Date**: 2026-08-02  
**Scope**: Signal semantics, economics alignment, traceability, lifecycle reconciliation

## Executive Summary

Fixed critical bugs in signal probability interpretation, maker/taker economics alignment, and lifecycle counter accumulation. Added end-to-end traceability and production alerts to prevent silent regressions.

## Issues Fixed

### 1. NO-Side Probability Interpretation
**Problem**: Signal layer interpreted NO-side probability as YES-space, causing negative edge calculations.  
**Impact**: Valid NO orders were rejected due to negative executable edge.  
**Fix**: Canonical conversion to YES-space before edge calculation.  
**Test**: `test_no_signal_probability_conversion`, `test_probability_duality_violation`

### 2. Maker/Taker Economics Mismatch
**Problem**: Policy engine selected maker economics, but router used taker economics with spread costs.  
**Impact**: Maker orders incorrectly penalized with spread costs, reducing edge.  
**Fix**: Router now respects policy engine's economics mode selection.  
**Test**: `test_policy_precedence_over_aggressiveness`, `test_maker_economics_edge_consistency`

### 3. Lifecycle Counter Accumulation
**Problem**: Lifecycle reconciliation compared per-tick candidates against cumulative global events.  
**Impact**: False warning: `1 candidates != 71 terminal lifecycle events`  
**Fix**: Tick-scoped reconciliation with `tick_id` tagging on all lifecycle events.  
**Test**: `test_tick_scoped_reconciliation_single_tick`, `test_cross_tick_leakage_regression`

## New Capabilities

### End-to-End Candidate Tracing
- **CandidateTrace**: Immutable dataclass capturing complete candidate lifecycle
- **CandidateTraceStore**: In-memory store for batch reconciliation and post-mortem analysis
- **Stage-by-stage validation**: Signal → Allocator → Policy → Microstructure → Execution
- **Test**: `test_complete_pipeline_tick_scoped_reconciliation` (golden path integration)

### Production Alerts
Added to `TradingInvariantsMonitor`:
1. **Missing tick_id detection** (zero tolerance)
   - Detects lifecycle events without tick_id
   - Zero tolerance threshold
2. **Lifecycle imbalance per tick** (>1% threshold)
   - Detects ticks where candidates != terminal events
   - Threshold: >1% of ticks with imbalance triggers alert
3. **Economics mode disagreement** (future work)
   - Would detect policy vs router economics mode mismatches
   - Threshold: >1% of trades with mismatch triggers alert

## Test Coverage

**61 tests total** (20 new tests added):
- Probability conversion (3 tests)
- Edge sign consistency (4 tests)
- Maker/taker policy (3 tests)
- Counter reconciliation (3 tests)
- Trace construction (3 tests)
- Canonical probability (8 parametrized tests)
- Economics selection (7 parametrized tests)
- Executable edge (7 parametrized tests)
- Terminal state (8 tests)
- Ledger reconciliation (2 tests)
- Golden trace (1 test)
- Critical edge path (2 tests)
- Tick-scoped reconciliation (5 tests)
- Golden path integration (1 test)

## Architecture Improvements

### Centralized Lifecycle Logging
All 7 terminal state transitions now go through `_log_candidate_lifecycle_event`:
- RECEIVED → BLOCKED_EDGE_THRESHOLD
- RECEIVED → BLOCKED_DUPLICATE
- RECEIVED → BLOCKED_POSITION
- RECEIVED → BLOCKED_RESTING_ORDER
- RECEIVED → EXECUTED
- RECEIVED → REJECTED
- RECEIVED → BLOCKED_PARITY

This ensures every terminal path includes `tick_id` for tick-scoped reconciliation.

### Invariant Enforcement
The tracing layer now makes semantic mismatches visible:
- Probability duality: `signal_model_prob + canonical_yes_prob = 1.0` for NO-side
- Policy-economics alignment: policy role determines economics mode
- Edge sign consistency: executable edge sign matches side and economics mode

## Deployment Notes

### Monitoring
- Review `TradingInvariantsMonitor` logs for lifecycle alerts
- Alert on any missing tick_id (zero tolerance)
- Alert on >1% tick lifecycle imbalance rate
- Alert on >1% economics mode mismatch rate (when implemented)

### Validation
- Run test suite: `pytest tests/test_candidate_trace_probability_conversion.py -v`
- Verify all 61 tests pass
- Check production logs for lifecycle reconciliation warnings
- Monitor `TradingInvariantsMonitor` summary logs

### Rollback
If issues arise:
1. Disable lifecycle reconciliation by commenting out tick-scoped filter
2. Revert to global cumulative reconciliation (old behavior)
3. Disable candidate tracing by setting `CANDIDATE_TRACE_AVAILABLE = False`

## References

- Implementation: `CANDIDATE_TRACING_IMPLEMENTATION_2026_08_02.md`
- Maker/taker fix: `MARKER_TAKER_ECONOMICS_FIX_2026_08_02.md`
- Test file: `tests/test_candidate_trace_probability_conversion.py`
- Tracing module: `merid/event_venues/kalshi/candidate_trace.py`
- Monitoring: `merid/monitoring/trading_invariants_monitor.py`
