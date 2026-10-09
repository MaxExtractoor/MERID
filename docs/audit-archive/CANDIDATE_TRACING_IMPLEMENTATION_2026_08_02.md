# End-to-End Candidate Tracing Implementation

**Date:** 2026-08-02  
**Purpose:** Make probability and edge consistency fixes provable through immutable tracing

## Overview

This implementation adds end-to-end candidate tracing to validate that probability interpretations, edge calculations, and economics mode remain consistent across all stages of the trading pipeline. The tracing system enforces key invariants and provides a single source of truth for debugging.

## Architecture

### CandidateTrace Dataclass

Immutable frozen dataclass that captures the complete lifecycle of a trading candidate:

```python
@dataclass(frozen=True)
class CandidateTrace:
    # Immutable identifier
    candidate_id: str
    
    # Signal generation stage
    signal_timestamp: Optional[float]
    signal_model_prob: Optional[float]  # Raw probability from signal layer
    signal_side: Optional[Side]  # Side from signal (YES/NO)
    signal_edge_pct: Optional[float]  # Edge percentage from signal
    
    # Canonical probability conversion
    canonical_yes_prob: Optional[float]  # YES-space probability (router canonical)
    canonical_no_prob: Optional[float]  # NO-space probability (for logging)
    
    # Allocator/gate stage
    allocator_timestamp: Optional[float]
    chosen_side: Optional[Side]  # Final side after dual-side selection
    chosen_edge_pct: Optional[float]  # Final edge after selection
    
    # Policy/economics stage
    policy_timestamp: Optional[float]
    policy_intended_role: Optional[str]  # "maker" or "taker" from policy engine
    economics_mode: Optional[EconomicsMode]  # Actual economics mode used
    aggressiveness: Optional[float]  # Aggressiveness parameter
    
    # Microstructure stage
    microstructure_timestamp: Optional[float]
    yes_bid_cents: Optional[int]
    no_bid_cents: Optional[int]
    order_price_cents: Optional[float]
    spread_cents: Optional[int]
    fee_cents: Optional[float]
    raw_edge_cents: Optional[float]  # Edge before costs
    executable_edge_cents: Optional[float]  # Edge after costs
    
    # Router/execution stage
    router_timestamp: Optional[float]
    execution_timestamp: Optional[float]
    
    # Terminal state
    terminal_state: Optional[TerminalState]
    terminal_reason: Optional[str]
    
    # Metadata
    ticker: Optional[str]
    asset: Optional[str]
    metadata: Dict[str, Any]
```

### Key Invariants

The `validate_invariants()` method enforces these critical invariants:

1. **Probability duality**: `signal_model_prob + canonical_yes_prob == 1.0` for NO-side candidates
2. **Policy-economics consistency**: `policy_intended_role` determines economics mode unless explicitly overridden
3. **Edge sign consistency**: `executable_edge` computed from same side basis as signal layer
4. **Terminal state requirement**: Every candidate must have exactly one terminal state
5. **Maker economics**: `executable_edge == raw_edge` (no costs)
6. **Taker economics**: `executable_edge <= raw_edge` (after costs)

### CandidateTraceStore

In-memory store for managing trace records:

```python
class CandidateTraceStore:
    def add_trace(self, trace: CandidateTrace) -> None
    def get_trace(self, candidate_id: str) -> Optional[CandidateTrace]
    def get_all_traces(self) -> list[CandidateTrace]
    def get_traces_by_ticker(self, ticker: str) -> list[CandidateTrace]
    def get_traces_by_terminal_state(self, state: TerminalState) -> list[CandidateTrace]
    def reconcile_counters(self) -> Dict[str, int]
    def validate_all_invariants(self) -> Dict[str, list[str]]
    def clear(self) -> None
```

## Integration Points

### 1. Signal Generation (agent_grid_15m.py)

**Location:** Lines 5533-5630

**What's added:**
- Generate unique `candidate_id` for each signal
- Initialize `CandidateTrace` with signal generation stage data
- Add trace to global store

**Log output:**
```
[CANDIDATE-TRACE] Initialized trace: candidate_id=uuid asset=BTC side=NO model_prob=0.760 edge=12.40%
```

### 2. Allocator (loop_15m.py)

**Location:** Lines 6201-6246

**What's added:**
- Update trace with canonical probability conversion
- Set `canonical_yes_prob` to `model_prob_yes_canonical` (YES-space probability)
- Set `canonical_no_prob` to `1.0 - model_prob_yes_canonical`
- Update allocator timestamp and chosen side/edge

**Log output:**
```
[CANDIDATE-TRACE] Updated trace with canonical probability: candidate_id=uuid canonical_yes=0.240 canonical_no=0.760
```

### 3. Microstructure Gate (order_router.py)

**Location:** Lines 764-822

**What's added:**
- Update trace with microstructure stage data
- Set `economics_mode` based on `use_maker_economics` flag
- Record spread, fee, raw_edge, executable_edge
- Update terminal state based on gate result

**Log output:**
```
[CANDIDATE-TRACE] Updated trace with microstructure data: candidate_id=uuid raw_edge=20.00c executable_edge=20.00c passes=True
```

## Test Suite

Comprehensive test suite in `tests/test_candidate_trace_probability_conversion.py` with 13 test classes and 40+ test cases:

### Test Categories

#### 1. Probability Conversion Tests (3 tests)

**`test_no_signal_probability_conversion`**
- Validates: NO signal at 0.76 → router receives canonical YES prob 0.24
- Checks: `signal_model_prob + canonical_yes_prob == 1.0`

**`test_yes_signal_probability_conversion`**
- Validates: YES signal at 0.65 → router receives canonical YES prob 0.65
- Checks: No conversion needed for YES orders

**`test_probability_duality_violation`**
- Validates: Probability duality violation is detected
- Checks: Invariant checker catches wrong conversion

#### 2. Edge Sign Tests (5 tests)

**`test_no_order_positive_executable_edge`**
- Validates: NO order with positive trade-winning probability → executable edge positive
- Example: NO order at 56c with model_prob=0.76 → raw_edge=+20c

**`test_maker_economics_edge_consistency`**
- Validates: Maker economics → executable_edge == raw_edge (no costs)

**`test_taker_economics_edge_consistency`**
- Validates: Taker economics → executable_edge <= raw_edge (after costs)

**`test_taker_economics_edge_violation`**
- Validates: Taker economics with executable_edge > raw_edge is detected

#### 3. Maker/Taker Policy Tests (3 tests)

**`test_policy_maker_with_aggressiveness`**
- Validates: Policy says maker, aggressiveness > 0 → router uses maker economics
- This was the bug: router used aggressiveness to force taker economics

**`test_policy_taker_with_aggressiveness`**
- Validates: Policy says taker, aggressiveness > 0 → router uses taker economics

**`test_policy_economics_mismatch`**
- Validates: Policy says maker but economics mode is taker is detected

#### 4. Counter Reconciliation Tests (3 tests)

**`test_single_candidate_rejection`**
- Validates: 1 candidate, 0 fills, 1 reject → ledger reconciles exactly

**`test_multiple_candidates_reconciliation`**
- Validates: Multiple candidates with different terminal states → ledger reconciles

**`test_missing_terminal_state_violation`**
- Validates: Candidate without terminal state is detected

#### 5. Trace Store Tests (3 tests)

**`test_add_and_retrieve_trace`**
- Validates: Adding and retrieving traces works correctly

**`test_get_traces_by_ticker`**
- Validates: Filtering traces by ticker works correctly

**`test_validate_all_invariants`**
- Validates: Batch invariant validation works correctly

#### 6. Trace Construction Tests (3 tests)

**`test_signal_stage_construction`**
- Validates: Signal stage appends correct fields

**`test_allocator_stage_updates`**
- Validates: Allocator stage updates without mutating signal stage

**`test_microstructure_stage_updates`**
- Validates: Microstructure stage updates without mutating prior stages

#### 7. Canonical Probability Tests (8 parametrized tests)

**`test_no_side_canonical_conversion`**
- Validates: NO-side signal probability converts to YES-space exactly once
- Parametrized: 0.76→0.24, 0.81→0.19, 0.50→0.50, 0.90→0.10

**`test_yes_side_canonical_conversion`**
- Validates: YES-side signal probability does not need conversion
- Parametrized: 0.65→0.65, 0.50→0.50, 0.80→0.80, 0.30→0.30

#### 8. Economics Selection Tests (7 parametrized tests)

**`test_policy_precedence_over_aggressiveness`**
- Validates: Policy-intended role overrides aggressiveness fallback
- Parametrized: (maker,0.0,maker), (maker,0.50,maker), (maker,1.0,maker), (taker,0.0,taker), (taker,0.50,taker), (taker,1.0,taker)

**`test_policy_maker_aggressiveness_fallback_violation`**
- Validates: Policy says maker but aggressiveness fallback forces taker is detected

#### 9. Executable Edge Tests (8 parametrized tests)

**`test_edge_math_consistency`**
- Validates: Router edge math is consistent with chosen economics mode
- Parametrized: (20,0,0,maker,20), (20,5,2,taker,13), (15,0,0,maker,15), (15,10,2,taker,3), (3,0,0,maker,3), (3,2,1,taker,0)

**`test_maker_edge_violation`**
- Validates: Maker economics with executable_edge != raw_edge is detected

**`test_taker_edge_violation`**
- Validates: Taker economics with executable_edge > raw_edge is detected

#### 10. Terminal State Tests (2 tests)

**`test_valid_terminal_states`**
- Validates: All valid terminal states are accepted
- Parametrized: SIGNAL_GENERATED, ALLOCATOR_REJECTED, PARITY_REJECTED, MICROSTRUCTURE_REJECTED, RISK_REJECTED, EXECUTED, FAILED

**`test_missing_terminal_state_violation`**
- Validates: Missing terminal state is detected

#### 11. Ledger Reconciliation Tests (2 tests)

**`test_counter_integrity_single_batch`**
- Validates: generated = executed + rejected + blocked + expired for single batch

**`test_replay_from_events`**
- Validates: Reconstructing counts from replayed trace events matches runtime counters

#### 12. Golden Trace Tests (1 test)

**`test_btc_no_golden_trace`**
- Validates: Complete golden trace for BTC NO candidate (end-to-end validation)
- Tests exact scenario from bug report: NO at 56c with model_prob=0.76 → raw_edge=+20c → EXECUTED

#### 13. Critical Edge Path Tests (2 tests)

**`test_raw_edge_negative_path_detection`**
- Validates: raw_edge=-32.00c path is detected as probability interpretation bug
- Tests the bug symptom: router computed raw_edge=-32c when signal showed +12.4% edge

**`test_corrected_raw_edge_positive_path`**
- Validates: Corrected path: raw_edge=+20c after canonical probability fix
- Tests the fix: router receives canonical YES-space probability (0.24) and computes correct edge

### Key Invariants Enforced

| Invariant | Assertion | Test |
|---|---|---|
| NO probability duality | `signal_model_prob + canonical_yes_prob == 1.0` | `test_no_side_canonical_conversion` |
| Policy precedence | `expected_role` or `fee_type` wins over aggressiveness | `test_policy_precedence_over_aggressiveness` |
| Side basis consistency | signal side and router side use the same semantic interpretation | `test_btc_no_golden_trace` |
| Counter integrity | `generated = executed + rejected + blocked + expired` for the same batch | `test_counter_integrity_single_batch` |
| Immutability | earlier trace snapshots remain unchanged after later stage updates | `test_allocator_stage_updates` |
| Maker economics | `executable_edge == raw_edge` (no costs) | `test_maker_economics_edge_consistency` |
| Taker economics | `executable_edge <= raw_edge` (after costs) | `test_taker_economics_edge_consistency` |
| Terminal state | every candidate ends in exactly one terminal state | `test_missing_terminal_state_violation` |

## Running Tests

```bash
# Run all candidate trace tests (59 tests)
pytest tests/test_candidate_trace_probability_conversion.py -v

# Run specific test category
pytest tests/test_candidate_trace_probability_conversion.py::TestProbabilityConversion -v
pytest tests/test_candidate_trace_probability_conversion.py::TestEdgeSign -v
pytest tests/test_candidate_trace_probability_conversion.py::TestMakerTakerPolicy -v
pytest tests/test_candidate_trace_probability_conversion.py::TestCounterReconciliation -v
pytest tests/test_candidate_trace_probability_conversion.py::TestTickScopedLifecycleReconciliation -v

# Run with coverage
pytest tests/test_candidate_trace_probability_conversion.py --cov=merid.event_venues.kalshi.candidate_trace -v
```

## Lifecycle Reconciliation Fix (2026-08-02)

### Problem
The lifecycle reconciliation was accumulating events across ticks, causing false warnings:
```
[LIFECYCLE-SANITY-WARNING] tick=151 lifecycle mismatch: 1 candidates != 71 terminal lifecycle events (breakdown={'REJECTED': 71})
```

### Root Cause
The lifecycle event log was global and cumulative, but the sanity check compared it to a per-tick candidate count. This violated the invariant: `candidates(t) = terminal_events(t)` for each tick t.

### Solution
1. **Added tick_id to lifecycle events**: Each lifecycle event now includes the tick_id when it was created
2. **Tick-scoped reconciliation**: The sanity check now filters events by tick_id before counting
3. **Tick tracking**: Added `self._current_tick` to track the current tick in the loop

### Changes
- `loop_15m.py`: Added `self._current_tick = tick_id` at start of each tick
- `loop_15m.py`: Added `tick_id` field to lifecycle events in `_log_candidate_lifecycle_event`
- `loop_15m.py`: Changed reconciliation to filter by `event.get("tick_id") == tick_id`

### Terminal Path Coverage Verification
All 7 terminal state transitions go through the centralized `_log_candidate_lifecycle_event`:
1. **RECEIVED → BLOCKED_EDGE_THRESHOLD** (edge validation failure)
2. **RECEIVED → BLOCKED_DUPLICATE** (duplicate order rejection)
3. **RECEIVED → BLOCKED_POSITION** (position exists rejection)
4. **RECEIVED → BLOCKED_RESTING_ORDER** (resting order exists rejection)
5. **RECEIVED → EXECUTED** (order submitted successfully)
6. **RECEIVED → REJECTED** (router rejection)
7. **RECEIVED → BLOCKED_PARITY** (parity gate rejection)

All paths now include `tick_id` in their lifecycle events.

### Invariant
For a given tick t:
- `candidates(t) = terminal_events(t)`
- `candidates(t) = rejected(t) + filled(t) + blocked(t) + expired(t)`
- The check fails only if the filtered event set for that tick does not reconcile

Global cumulative metrics are tracked separately for long-run totals but are not used in per-tick validation.

### Test Coverage
Added 6 tick-scoped reconciliation tests:
- `test_tick_scoped_reconciliation_single_tick`: Validates 1 candidate = 1 terminal event for single tick
- `test_tick_scoped_reconciliation_multiple_ticks`: Validates each tick reconciles independently
- `test_global_vs_local_separation`: Validates global totals may accumulate but tick-level validation ignores previous ticks
- `test_reset_snapshot_at_tick_boundaries`: Validates per-tick counters are reset at tick boundaries
- `test_cross_tick_leakage_regression`: Detects accidental cross-tick event leakage (async delays, queueing bugs)
- `test_complete_pipeline_tick_scoped_reconciliation`: Golden path integration test validating complete pipeline from signal generation through tick-scoped reconciliation

### Golden Path Integration Test
The final integration test (`test_complete_pipeline_tick_scoped_reconciliation`) validates the complete pipeline end-to-end:
1. **Signal generation**: NO-side signal at 0.76 probability
2. **Canonical conversion**: NO-side → canonical YES-space probability (0.24)
3. **Allocator selection**: Chosen side NO, edge 1.0%
4. **Policy decision**: Maker economics with aggressiveness 0.50
5. **Microstructure edge calculation**: Raw edge +20c, executable edge +20c (maker economics)
6. **Execution**: Terminal state EXECUTED
7. **Tick-scoped reconciliation**: 1 candidate = 1 terminal event for tick 150

This test ensures all pipeline stages are consistent and the tick-scoped reconciliation works correctly in the context of the full candidate lifecycle.

## Production Alerts (2026-08-02)

Added production alerts to `trading_invariants_monitor.py` to catch regressions early:

### Implemented Alerts
1. **Missing tick_id detection** (zero tolerance)
   - Detects lifecycle events without tick_id
   - Zero tolerance threshold (any missing tick_id triggers alert)
   - Integrated into `_create_lifecycle_logger` in `loop_15m.py`

2. **Lifecycle imbalance per tick** (>1% threshold)
   - Detects ticks where candidates != terminal events
   - Threshold: >1% of ticks with imbalance triggers alert
   - Integrated into lifecycle sanity check in `loop_15m.py`

### Future Work
3. **Economics mode disagreement** (not yet implemented)
   - Would detect policy vs router economics mode mismatches
   - Requires tracking policy decisions in loop_15m.py
   - Threshold: >1% of trades with mismatch triggers alert

### Alert Integration
- `TradingInvariantsMonitor` extended with 3 new invariant counters
- Alert thresholds added for lifecycle reconciliation invariants
- Lifecycle logger now records missing tick_id events to monitor
- Lifecycle sanity check now records imbalance events to monitor
- Summary logging includes new lifecycle metrics
- All lifecycle alerts are CRITICAL level (ERROR log severity)

## Usage Example

### Creating and Validating a Trace

```python
from merid.event_venues.kalshi.candidate_trace import (
    CandidateTrace,
    Side as TraceSide,
    EconomicsMode,
    TerminalState,
    get_trace_store,
)

# Create a trace for a NO order
trace = CandidateTrace(
    signal_model_prob=0.76,  # NO outcome probability from signal
    signal_side=TraceSide.NO,
    canonical_yes_prob=0.24,  # YES-space probability for router
    canonical_no_prob=0.76,  # NO-space probability for logging
    order_price_cents=56.0,
    raw_edge_cents=20.0,
    executable_edge_cents=20.0,
    economics_mode=EconomicsMode.MAKER,
    terminal_state=TerminalState.EXECUTED,
    ticker="KXBTC15M-26AUG020030-00",
    asset="BTC",
)

# Validate invariants
violations = trace.validate_invariants()
if violations:
    print(f"Invariant violations: {violations}")
else:
    print("All invariants passed")

# Add to store
store = get_trace_store()
store.add_trace(trace)

# Reconcile counters
counters = store.reconcile_counters()
print(f"Terminal state counters: {counters}")
```

## Debugging with Traces

### Viewing All Traces

```python
from merid.event_venues.kalshi.candidate_trace import get_trace_store

store = get_trace_store()
traces = store.get_all_traces()

for trace in traces:
    print(f"Candidate: {trace.candidate_id}")
    print(f"  Signal: model_prob={trace.signal_model_prob}, side={trace.signal_side}")
    print(f"  Canonical: yes={trace.canonical_yes_prob}, no={trace.canonical_no_prob}")
    print(f"  Economics: role={trace.policy_intended_role}, mode={trace.economics_mode}")
    print(f"  Edge: raw={trace.raw_edge_cents}, executable={trace.executable_edge_cents}")
    print(f"  Terminal: {trace.terminal_state} - {trace.terminal_reason}")
```

### Filtering by Terminal State

```python
from merid.event_venues.kalshi.candidate_trace import (
    get_trace_store,
    TerminalState,
)

store = get_trace_store()
rejected_traces = store.get_traces_by_terminal_state(TerminalState.MICROSTRUCTURE_REJECTED)

print(f"Rejected candidates: {len(rejected_traces)}")
for trace in rejected_traces:
    print(f"  {trace.ticker}: {trace.terminal_reason}")
```

### Validating All Invariants

```python
from merid.event_venues.kalshi.candidate_trace import get_trace_store

store = get_trace_store()
violations = store.validate_all_invariants()

if violations:
    print(f"Found invariant violations in {len(violations)} candidates:")
    for candidate_id, trace_violations in violations.items():
        print(f"  {candidate_id}: {trace_violations}")
else:
    print("All candidates passed invariant validation")
```

## Benefits

1. **Provable correctness**: Invariants are enforced programmatically, not just documented
2. **Single source of truth**: All stages contribute to the same immutable trace record
3. **Post-mortem analysis**: Complete lifecycle history for debugging failed orders
4. **Counter reconciliation**: Ledger is replayable into same counters every time
5. **Regression prevention**: Tests lock down the semantics of probability and edge calculations

## Future Enhancements

1. **Persistence**: Add database backend for trace storage (currently in-memory)
2. **Real-time monitoring**: Add Prometheus metrics for invariant violations
3. **Alerting**: Trigger alerts when invariants are violated in production
4. **Visualization**: Add dashboard for trace analysis and counter reconciliation
5. **Batch validation**: Add end-of-day reconciliation reports

## Files Added

- `merid/event_venues/kalshi/candidate_trace.py`: CandidateTrace dataclass and CandidateTraceStore
- `tests/test_candidate_trace_probability_conversion.py`: Comprehensive test suite

## Files Modified

- `merid/prediction/agent_grid_15m.py`: Added trace initialization in signal generation
- `merid/loop_15m.py`: Added trace update with canonical probability conversion
- `merid/event_venues/kalshi/order_router.py`: Added trace update with microstructure stage data

## Related Documentation

- `PROBABILITY_INTERPRETATION_FIX_2026_08_02.md`: Details on the probability interpretation fix
- `MARKER_TAKER_ECONOMICS_FIX_2026_08_02.md`: Details on the maker/taker economics fix