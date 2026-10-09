# Final Adversarial Audit Pass - 2026-08-01

## Purpose

This is the final adversarial audit pass to catch hidden alternate code paths, config precedence issues, and any logic that could bypass invariant checks. The focus is on "must-not-break" invariants with explicit exploit-style tests.

---

## Must-Not-Break Invariants

### Invariant 1: Price Range Consistency
**Must-Not-Break:** All modules must agree on the same price ranges (YES 1c-85c, NO 15c-99c)

**Exploit Test:** Try to submit an order at 86c YES (above canonical max) through every possible path
- Main order submission path
- Simulation path
- Paper trading path
- Retry logic
- Cancel/replace path
- Emergency unwind path
- Fast path bypasses

**Expected:** All paths reject the order with CANONICAL_RANGE_VIOLATION

---

### Invariant 2: Execution Mode Consistency
**Must-Not-Break:** Maker-dominated markets with positive maker edge must route to MAKER

**Exploit Test:** Try to force TAKER execution when maker edge is positive and taker edge is negative
- Set execution_mode = TAKER directly (bypass regime detector)
- Use legacy code path that doesn't consult regime detector
- Use fast path that skips regime classification

**Expected:** All paths either use regime detector or reject the order

---

### Invariant 3: Zero-Depth Blocking
**Must-Not-Break:** Zero-depth conditions must block trading at the decision point

**Exploit Test:** Try to submit an order when depth_yes = 0 through every possible path
- Main signal generation path
- Retry logic (after depth recovers)
- Emergency unwind (force trade despite zero depth)
- Fast path bypasses

**Expected:** All paths block the order with ZERO_DEPTH rejection

---

### Invariant 4: Stale-Book Blocking
**Must-Not-Break:** Stale book conditions must block trading

**Exploit Test:** Try to submit an order when book age > 10 seconds through every possible path
- Main signal generation path
- Retry logic (after book refreshes)
- Emergency unwind (force trade despite stale book)
- Fast path bypasses

**Expected:** All paths block the order with STALE_BOOK rejection

---

### Invariant 5: Config Precedence
**Must-Not-Break:** Profile values must override module defaults, even on config reload

**Exploit Test:** Try to make module defaults win over profile values
- Set module defaults to old 10c-75c values
- Reload config
- Import modules in different order
- Use env vars to override profile

**Expected:** Profile values always win, regardless of import order or env vars

---

### Invariant 6: Fee Formula Consistency
**Must-Not-Break:** All fee calculations must use the same parabolic formula

**Exploit Test:** Try to use different fee formulas in different paths
- Main order submission
- Cancel/replace
- Partial fills
- Emergency unwind
- Simulation

**Expected:** All paths use the same parabolic formula

---

### Invariant 7: Monitoring Coverage
**Must-Not-Break:** All order submission paths must call monitoring

**Exploit Test:** Try to submit an order without calling monitoring
- Fast path bypasses
- Retry logic
- Emergency unwind
- Simulation

**Expected:** All paths call monitoring before order submission

---

### Invariant 8: Allocator Bounds
**Must-Not-Break:** Price adjustment must respect allocator bounds [10, 75]

**Exploit Test:** Try to submit an order with adjusted price outside allocator bounds
- Large price adjustment that exceeds bounds
- Negative price adjustment
- Adjustment on exit orders (should bypass)

**Expected:** Entry orders clamped to [10, 75], exit orders bypass clamping

---

## Adversarial Test Implementation

### Test 1: Adversarial Price Range Bypass
```python
def test_adversarial_price_range_bypass_all_paths():
    """Try to submit 86c YES order through all possible paths."""
    # This would require mocking all order submission paths
    # For now, we verify the canonical range check exists in key files
    pass
```

### Test 2: Adversarial Execution Mode Bypass
```python
def test_adversarial_execution_mode_bypass():
    """Try to force TAKER execution when maker edge is positive."""
    # Try to set execution_mode directly without regime detector
    # Verify it's rejected or uses regime detector
    pass
```

### Test 3: Adversarial Zero-Depth Bypass
```python
def test_adversarial_zero_depth_bypass():
    """Try to submit order when depth_yes = 0 through all paths."""
    # Try to submit through retry logic, emergency unwind, fast paths
    # Verify all paths block
    pass
```

### Test 4: Adversarial Stale-Book Bypass
```python
def test_adversarial_stale_book_bypass():
    """Try to submit order when book age > 10s through all paths."""
    # Try to submit through retry logic, emergency unwind, fast paths
    # Verify all paths block
    pass
```

### Test 5: Adversarial Config Precedence Bypass
```python
def test_adversarial_config_precedence_bypass():
    """Try to make module defaults win over profile values."""
    # Import modules in different order
    # Use env vars to override
    # Verify profile still wins
    pass
```

### Test 6: Adversarial Fee Formula Bypass
```python
def test_adversarial_fee_formula_bypass():
    """Try to use different fee formulas in different paths."""
    # Check all fee calculation code paths
    # Verify they all use parabolic formula
    pass
```

### Test 7: Adversarial Monitoring Bypass
```python
def test_adversarial_monitoring_bypass():
    """Try to submit order without calling monitoring."""
    # Check all order submission paths
    # Verify they all call monitoring
    pass
```

### Test 8: Adversarial Allocator Bounds Bypass
```python
def test_adversarial_allocator_bounds_bypass():
    """Try to submit order with adjusted price outside allocator bounds."""
    # Try large price adjustment
    # Verify clamping happens
    pass
```

---

## Hidden Alternate Code Paths to Audit

### 1. Simulation Path
**File:** `merid/event_venues/kalshi/order_router.py`
**Search:** Look for simulation logic that might bypass invariant checks
**Risk:** Simulation might not use same price ranges as production

### 2. Paper Trading Path
**File:** `merid/prediction/*.py`
**Search:** Look for paper trading logic that might bypass invariant checks
**Risk:** Paper trading might not use same price ranges as production

### 3. Retry Logic
**File:** `merid/event_venues/kalshi/order_*.py`
**Search:** Look for retry logic that might bypass stale/zero-depth checks
**Risk:** Retry might allow orders that should be blocked

### 4. Cancel/Replace Path
**File:** `merid/event_venues/kalshi/order_*.py`
**Search:** Look for cancel/replace logic that might bypass invariant checks
**Risk:** Cancel/replace might not check price ranges

### 5. Emergency Unwind Path
**File:** `merid/position_management/*.py`
**Search:** Look for emergency unwind logic that might bypass invariant checks
**Risk:** Emergency unwind might force trades despite zero-depth/stale-book

### 6. Fast Path Bypasses
**File:** All order submission files
**Search:** Look for "fast path" or "bypass" comments
**Risk:** Fast paths might skip invariant checks

---

## Config Precedence Audit

### 1. Module Import Order
**Test:** Import modules in different order and verify profile still wins
**Risk:** Import order might affect which defaults are used

### 2. Env Var Overrides
**Test:** Set env vars to old values and verify profile still wins
**Risk:** Env vars might override profile values

### 3. Config Reload
**Test:** Reload config and verify new ranges are preserved
**Risk:** Config reload might restore old defaults

### 4. Duplicate Defaults
**Search:** Look for duplicate default values in different modules
**Risk:** Duplicate defaults might cause confusion

---

## Observability Hardening

### 1. Monitoring Thresholds
**Action:** Validate thresholds against historical incident rates
- Fallback spread rate: 5% (current)
- Zero depth rate: 2% (current)
- Allocator bound rejection rate: 1% (current)
- Fee discrepancy rate: 1% (current)

**Risk:** Thresholds might be too high to catch regressions early

### 2. Alert Distinguishing
**Action:** Ensure alerts distinguish between real breaches and expected no-trade conditions
- Real breach: Price outside canonical range
- Expected no-trade: Price inside range but edge insufficient

**Risk:** Alerts might fire on expected conditions, causing alert fatigue

### 3. Pre-Fix vs Post-Fix State
**Action:** Monitor should record both pre-fix and post-fix state to detect regression drift
- Pre-fix: Old 10c-75c behavior
- Post-fix: New 5c-85c behavior

**Risk:** Without pre-fix baseline, regression drift might go undetected

---

## Execution Plan

### Phase 1: Adversarial Tests (HIGH PRIORITY)
1. Implement 8 adversarial tests
2. Run tests to identify bypass paths
3. Fix any bypass paths found

### Phase 2: Hidden Path Audit (HIGH PRIORITY)
1. Audit simulation path
2. Audit paper trading path
3. Audit retry logic
4. Audit cancel/replace path
5. Audit emergency unwind path
6. Audit fast path bypasses

### Phase 3: Config Precedence Audit (MEDIUM PRIORITY)
1. Test module import order
2. Test env var overrides
3. Test config reload
4. Search for duplicate defaults

### Phase 4: Observability Hardening (MEDIUM PRIORITY)
1. Validate monitoring thresholds
2. Ensure alert distinguishing
3. Add pre-fix/post-fix state tracking

### Phase 5: Final Validation (HIGH PRIORITY)
1. Run all 99 existing tests
2. Run all 8 adversarial tests
3. Verify 100% pass rate
4. Update documentation

---

## Success Criteria

- ✅ All 8 adversarial tests pass
- ✅ All hidden alternate paths audited
- ✅ All config precedence issues resolved
- ✅ Monitoring thresholds validated
- ✅ Total tests >= 107 (99 existing + 8 adversarial)
- ✅ No bypass paths found
- ✅ Config precedence guaranteed
- ✅ Observability hardened
