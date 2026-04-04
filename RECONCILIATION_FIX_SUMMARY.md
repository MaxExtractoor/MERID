# Reconciliation Blocking Fix — Summary

## Problem

Reconciliation logic was **silently blocking live trading on fresh start** by treating the "never ran" state (fresh start) the same as "genuine critical discrepancies".

### Root Cause

The execution gate used `has_critical_discrepancies()` which returns `True` in two distinct cases:
1. **NEVER_RAN**: Reconciliation has never successfully run (fresh start, fail-closed default)
2. **RAN_CRITICAL**: Reconciliation ran and found genuine critical discrepancies

Both cases added a `BlockReason` with `severity="critical"`, **hard-blocking live trading**.

### Impact

- On fresh startup, trading was blocked until reconciliation ran
- This was a **silent blocker** — no clear distinction in logs between "never ran" and "real mismatches"
- Multiple code paths (execution gate, loop._execute_plans, loop._reconcile_positions) all exhibited this behavior

---

## Solution

Implemented **three distinct reconciliation states** with appropriate handling:

### 1. NEVER_RAN
**Semantics**: Reconciliation has never successfully run (fresh start or reconciliation disabled).

**Behavior**:
- **WARNING severity** (not critical) → does **not** hard-block execution
- Allows live trading with explicit logging
- Example log: `"Kalshi reconciliation: NEVER_RAN — allowing execution with warning"`

### 2. RAN_NO_CRITICAL
**Semantics**: Reconciliation ran and found no genuine critical discrepancies.

**Behavior**:
- No reason added to execution gate
- Execution **fully allowed**
- Example log: `"Kalshi reconciliation: RAN_NO_CRITICAL — execution allowed"`

### 3. RAN_CRITICAL
**Semantics**: Reconciliation ran and found genuine critical discrepancies.

**Behavior**:
- **CRITICAL severity** → **blocks execution**
- Logs explicit discrepancy counts
- Example log: `"Kalshi reconciliation: RAN_CRITICAL — blocking execution due to 2 critical discrepancies"`

---

## Code Changes

### 1. `core/execution_gate.py`
**Lines 161-200**: Kalshi venue reconciliation check

```python
# Before (blocking on NEVER_RAN):
if kalshi_has_critical():
    reasons.append(BlockReason(severity="critical", ...))

# After (distinguishing states):
if not has_ever_run():
    # NEVER_RAN: warning severity (does not block)
    reasons.append(BlockReason(severity="warning", ...))
elif kalshi_has_critical():
    # RAN_CRITICAL: critical severity (blocks with explicit counts)
    discrepancies = get_last_discrepancies()
    critical_count = sum(1 for d in discrepancies if d.severity == "critical")
    reasons.append(BlockReason(severity="critical", message=f"...{critical_count} critical discrepancies"))
else:
    # RAN_NO_CRITICAL: fully allowed (no reason)
    logger.debug("Kalshi reconciliation: RAN_NO_CRITICAL — execution allowed")
```

### 2. `merid/loop.py`
**Lines 1006-1031**: `_execute_plans` reconciliation gate

```python
# Before (blocking on NEVER_RAN):
if has_critical_discrepancies():
    logger.warning("Execution BLOCKED: critical reconciliation discrepancies detected")
    return

# After (distinguishing states):
if not has_ever_run():
    logger.warning("Reconciliation has never run (fresh start) — allowing execution")
elif has_critical_discrepancies():
    logger.error("Execution BLOCKED: %d critical reconciliation discrepancies detected", critical_count)
    return
```

**Lines 1257-1300**: `_reconcile_positions` reconciliation gate

```python
# Before (blocking on NEVER_RAN):
if has_critical_discrepancies():
    logger.error("CRITICAL reconciliation issues detected for Kalshi")
    guard.activate_domain_kill_switch("prediction", reason=...)

# After (distinguishing states):
if not has_ever_run():
    logger.info("First Kalshi reconciliation complete — execution enabled")
elif has_critical_discrepancies():
    logger.error("CRITICAL reconciliation issues detected for Kalshi")
    guard.activate_domain_kill_switch("prediction", reason=f"{critical_count} critical discrepancies detected")
```

### 3. Docstring Updates
Updated `core/execution_gate.py` module docstring to document the three reconciliation states and their semantics.

---

## Trace / Debug Capability

Added `_trace_reconciliation_state()` function to enable lightweight debugging:

**Enable**: `export MERID_TRACE_RECONCILIATION=1`

**Output**: Logs reconciliation state on every execution gate check
```
TRACE: Reconciliation state=NEVER_RAN blocked=False critical_discrepancies=0
TRACE: Reconciliation state=RAN_NO_CRITICAL blocked=False critical_discrepancies=0
TRACE: Reconciliation state=RAN_CRITICAL blocked=True critical_discrepancies=2
```

**Use case**: Manually confirm that reconciliation no longer silently blocks valid trades during normal startup and operation.

---

## Tests Added

**File**: `tests/core/test_execution_gate.py`

**Test class**: `TestKalshiReconciliationStates`

1. **`test_never_ran_state_warning_not_blocked`**
   - Reconciliation has never run
   - Asserts: `blocked=False`, `safe_to_trade=True`, `gate_state="limited"`
   - Asserts: exactly one reconciliation warning with "never run" and "fresh start"

2. **`test_ran_no_critical_state_fully_allowed`**
   - Reconciliation ran, no critical discrepancies
   - Asserts: `blocked=False`, `safe_to_trade=True`, `gate_state="clear"`
   - Asserts: zero reasons (fully allowed)

3. **`test_ran_critical_state_blocked`**
   - Reconciliation ran, found 2 critical discrepancies
   - Asserts: `blocked=True`, `safe_to_trade=False`, `gate_state="blocked"`
   - Asserts: critical reconciliation reason with "2 critical discrepancies" in message

---

## Deliverables

- ✅ Minimal diffs in reconciliation and execution gate code
- ✅ Updated tests for the three reconciliation states
- ✅ Docstring and comment explanations of intended semantics
- ✅ Trace capability for manual confirmation
- ✅ All blocking decisions now log clear reasons with explicit state

---

## Regression Prevention

**What prevents this from happening again:**

1. **Explicit state checks**: All blocking paths now check `has_ever_run()` before `has_critical_discrepancies()`
2. **Clear logging**: Every state transition logs its name (`NEVER_RAN`, `RAN_NO_CRITICAL`, `RAN_CRITICAL`)
3. **Comprehensive tests**: Three tests cover all states and their expected blocking behavior
4. **Docstring documentation**: Module-level docstring documents the semantics
5. **Trace capability**: `MERID_TRACE_RECONCILIATION=1` provides runtime visibility

**Code review checklist** for future changes:
- [ ] Does this code path check reconciliation state?
- [ ] Does it distinguish `NEVER_RAN` from `RAN_CRITICAL`?
- [ ] Does `NEVER_RAN` use warning severity (not critical)?
- [ ] Does it log the explicit state and reason?

---

## Related Files

- `core/execution_gate.py`: Main execution gate logic
- `merid/loop.py`: Event loop execution guards
- `merid/reconciliation.py`: Reconciliation implementation
- `tests/core/test_execution_gate.py`: Execution gate tests
- `RECONCILIATION_FIX_SUMMARY.md`: This document
